"""文件上传/下载服务 (Django fileUpload 应用迁移)

存储策略:
- 本地模式: 与老 Django MEDIA_ROOT 相同的磁盘目录 (Settings.media_root, 默认 kdx-be/media/),
  存储相对路径 "files/<uuid10>.<ext>", 与老 user_directory_path 生成的 key 完全一致
- S3/MinIO 模式 (USE_S3_MEDIA=true): 预签名 URL 直传; SigV4 签名用纯标准库实现
  (目标环境无 boto3, 且不允许引入新依赖), 对象读写走 urllib
"""

import hashlib
import hmac
import mimetypes
import re
import shutil
import ssl
import subprocess
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, unquote
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models.upload import FileRecord

UNSIGNED_PAYLOAD = 'UNSIGNED-PAYLOAD'
ALGORITHM = 'AWS4-HMAC-SHA256'
_SAFE_KEY_RE = re.compile(r'^[a-zA-Z0-9/_\-.]+$')


# ──────────────────────────────────────────────
# 存储 key / 本地文件操作
# ──────────────────────────────────────────────

def build_stored_name(filename: str) -> str:
    """生成存储文件名, 与 Django user_directory_path 一致: files/<uuid10>.<ext>"""
    ext = (filename or '').split('.')[-1]
    name = f'{uuid4().hex[:10]}.{ext}'
    # file 字段 max_length=100, 超长时截断扩展名
    if len(name) > 99:
        name = f'{uuid4().hex[:10]}.{ext[:99 - 11]}'
    return f'files/{name}'


def make_object_key(purpose: str, filename: str) -> str:
    """生成 S3/MinIO 对象 key (与老 _make_object_key 一致)"""
    safe_purpose = purpose.strip().lower()
    ext = Path(filename or '').suffix
    ext = ext[:20] if ext else ''
    uid = uuid4().hex
    prefix = {'baby_album': 'baby_album', 'growth': 'growth', 'files': 'files'}.get(safe_purpose, 'uploads')
    return f'{prefix}/{uid}{ext}'


def resolve_local_path(media_root: str, key: str) -> Path | None:
    """将存储 key 解析为 MEDIA_ROOT 下的绝对路径; 防目录穿越, 非法返回 None"""
    if not key or '..' in key:
        return None
    root = Path(media_root).resolve()
    p = (root / key).resolve()
    if p != root and root not in p.parents:
        return None
    return p


def guess_content_type(key: str) -> str:
    ct, _ = mimetypes.guess_type(key)
    return ct or 'application/octet-stream'


def save_local_file(media_root: str, key: str, content: bytes) -> Path:
    """保存文件到 MEDIA_ROOT 下的 key 位置"""
    path = resolve_local_path(media_root, key)
    if path is None:
        raise ValueError('invalid storage key')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def delete_local_file(media_root: str, key: str) -> bool:
    """删除本地文件, 不存在返回 False"""
    path = resolve_local_path(media_root, key)
    if path is None or not path.is_file():
        return False
    path.unlink()
    return True


# ──────────────────────────────────────────────
# MinIO/S3 SigV4 预签名 (纯标准库实现, 替代 boto3)
# ──────────────────────────────────────────────

def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _sigv4_signature(secret_key: str, datestamp: str, region: str, service: str, string_to_sign: str) -> str:
    k = _hmac_sha256(f'AWS4{secret_key}'.encode(), datestamp)
    for part in (region, service, 'aws4_request'):
        k = _hmac_sha256(k, part)
    return hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()


def _urlopen(req, verify_ssl: bool = True, timeout: int = 20):
    if verify_ssl:
        return urllib.request.urlopen(req, timeout=timeout)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def presign_s3_url(method: str, *, endpoint: str, bucket: str, key: str,
                   access_key: str, secret_key: str, region: str = 'us-east-1',
                   expires: int = 600, content_type: str | None = None) -> str:
    """生成 SigV4 预签名 URL (put/get/head/delete 通用)

    仅签名 host 与可选 content-type; body 使用 UNSIGNED-PAYLOAD,
    对未签名的请求头不做校验, 兼容各客户端。
    """
    host = endpoint.split('://', 1)[1].rstrip('/')
    uri = '/' + '/'.join(quote(seg, safe='') for seg in f'{bucket}/{key}'.split('/') if seg != '')

    now = datetime.now(timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    datestamp = now.strftime('%Y%m%d')
    scope = f'{datestamp}/{region}/s3/aws4_request'

    signed_headers = 'content-type;host' if content_type else 'host'
    params = {
        'X-Amz-Algorithm': ALGORITHM,
        'X-Amz-Credential': f'{access_key}/{scope}',
        'X-Amz-Date': amz_date,
        'X-Amz-Expires': str(int(expires)),
        'X-Amz-SignedHeaders': signed_headers,
    }
    canonical_query = '&'.join(
        f'{quote(k, safe="-_.~")}={quote(v, safe="-_.~")}'
        for k, v in sorted(params.items())
    )

    if content_type:
        canonical_headers = f'content-type:{content_type}\nhost:{host}\n'
    else:
        canonical_headers = f'host:{host}\n'

    canonical_request = (
        f'{method}\n{uri}\n{canonical_query}\n'
        f'{canonical_headers}\n{signed_headers}\n{UNSIGNED_PAYLOAD}'
    )
    string_to_sign = (
        f'{ALGORITHM}\n{amz_date}\n{scope}\n'
        f'{hashlib.sha256(canonical_request.encode()).hexdigest()}'
    )
    signature = _sigv4_signature(secret_key, datestamp, region, 's3', string_to_sign)
    return f'{endpoint.rstrip("/")}{uri}?{canonical_query}&X-Amz-Signature={signature}'


def to_public_url(url: str, settings: Settings) -> str:
    """将 MinIO 内部地址替换为外部访问地址 (对应老 _minio_url_to_proxy)"""
    if not url:
        return url
    public_endpoint = settings.minio_public_endpoint_url
    endpoint = settings.minio_endpoint_url
    if public_endpoint and endpoint and url.startswith(endpoint) and public_endpoint != endpoint:
        return url.replace(endpoint, public_endpoint)
    return url


def to_nginx_proxy_url(url: str, settings: Settings) -> str:
    """上传 URL 的兜底替换: 无 public_endpoint 时走 Nginx /minio/ 代理 (对应老逻辑)"""
    public_endpoint = settings.minio_public_endpoint_url
    endpoint = settings.minio_endpoint_url
    if public_endpoint and endpoint and url.startswith(endpoint):
        return url.replace(endpoint, public_endpoint)
    if endpoint and url.startswith(endpoint):
        url = url.replace(endpoint, '/minio')
        if not url.startswith('/minio/'):
            url = url.replace('/minio', '/minio/')
    return url


def s3_head_object(settings: Settings, bucket: str, key: str) -> dict:
    """HEAD 对象, 返回 etag/size/content_type; 不存在抛异常"""
    url = presign_s3_url(
        'HEAD', endpoint=settings.minio_endpoint_url, bucket=bucket, key=key,
        access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
        region=settings.minio_region_name, expires=600,
    )
    req = urllib.request.Request(url, method='HEAD')
    with _urlopen(req, verify_ssl=settings.minio_verify_ssl) as resp:
        return {
            'etag': resp.headers.get('ETag'),
            'size': resp.headers.get('Content-Length'),
            'content_type': resp.headers.get('Content-Type'),
        }


def s3_download_file(settings: Settings, bucket: str, key: str, dest_path: str) -> bool:
    """下载对象到本地临时文件, 失败抛异常"""
    url = presign_s3_url(
        'GET', endpoint=settings.minio_endpoint_url, bucket=bucket, key=key,
        access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
        region=settings.minio_region_name, expires=600,
    )
    with _urlopen(urllib.request.Request(url), verify_ssl=settings.minio_verify_ssl) as resp, \
            open(dest_path, 'wb') as f:
        shutil.copyfileobj(resp, f)
    return True


def s3_upload_bytes(settings: Settings, bucket: str, key: str, data: bytes, content_type: str) -> bool:
    """上传字节流到对象 (PUT 预签名, body 不参与签名)"""
    url = presign_s3_url(
        'PUT', endpoint=settings.minio_endpoint_url, bucket=bucket, key=key,
        access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
        region=settings.minio_region_name, expires=600,
    )
    req = urllib.request.Request(url, data=data, method='PUT',
                                 headers={'Content-Type': content_type})
    with _urlopen(req, verify_ssl=settings.minio_verify_ssl):
        pass
    return True


def s3_delete_object(settings: Settings, bucket: str, key: str) -> bool:
    """删除对象 (冒烟清理用)"""
    url = presign_s3_url(
        'DELETE', endpoint=settings.minio_endpoint_url, bucket=bucket, key=key,
        access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
        region=settings.minio_region_name, expires=600,
    )
    req = urllib.request.Request(url, method='DELETE')
    with _urlopen(req, verify_ssl=settings.minio_verify_ssl):
        pass
    return True


def ensure_video_poster(settings: Settings, src_key: str, poster_key: str) -> bool:
    """baby_album 视频封面: poster 已存在则跳过, 否则下载视频用 ffmpeg 抽帧上传"""
    try:
        s3_head_object(settings, settings.minio_bucket_name, poster_key)
        return True
    except Exception:
        pass
    if not ffmpeg_available():
        return False

    suffix = Path(src_key).suffix or '.mp4'
    import tempfile, os
    tmp_in_fd, tmp_in = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_in_fd)
    tmp_out_fd, tmp_out = tempfile.mkstemp(suffix='.jpg')
    os.close(tmp_out_fd)
    try:
        try:
            s3_download_file(settings, settings.minio_bucket_name, src_key, tmp_in)
        except Exception:
            return False
        if not extract_video_poster(tmp_in, tmp_out):
            return False
        with open(tmp_out, 'rb') as f:
            s3_upload_bytes(settings, settings.minio_bucket_name, poster_key, f.read(), 'image/jpeg')
        return True
    finally:
        for p in (tmp_in, tmp_out):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ──────────────────────────────────────────────
# 图片变体 / 视频封面 (PIL + ffmpeg)
# ──────────────────────────────────────────────

def make_image_variants(src_bytes: bytes, width: int) -> dict:
    """生成 webp/avif/jpg 缩放变体 (与老 ImageBestRedirectView 的 PIL 逻辑一致)

    返回 {'webp': bytes|None, 'avif': bytes|None, 'jpg': bytes}; 处理失败抛异常
    """
    from PIL import Image

    out = {'webp': None, 'avif': None, 'jpg': None}
    with Image.open(BytesIO(src_bytes)) as im:
        im = im.convert('RGB')
        w = int(width) if int(width) > 0 else 400
        h = int(im.height * (w / float(im.width))) if im.width else w
        im = im.resize((w, max(1, h)))

        buf = BytesIO()
        try:
            im.save(buf, 'WEBP', quality=80, method=6)
            out['webp'] = buf.getvalue()
        except Exception:
            pass
        buf = BytesIO()
        try:
            im.save(buf, 'AVIF', quality=50)
            out['avif'] = buf.getvalue()
        except Exception:
            pass
        buf = BytesIO()
        im.save(buf, 'JPEG', quality=82, optimize=True, progressive=True)
        out['jpg'] = buf.getvalue()
    return out


def ffmpeg_available() -> bool:
    return bool(shutil.which('ffmpeg'))


def extract_video_poster(input_path: str, output_path: str) -> bool:
    """ffmpeg 抽取视频第 1 秒帧作为封面"""
    try:
        p = subprocess.run(
            ['ffmpeg', '-y', '-ss', '00:00:01.000', '-i', input_path,
             '-frames:v', '1', '-q:v', '2', output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        ok = p.returncode == 0
    except Exception:
        return False
    out = Path(output_path)
    return bool(ok and out.exists() and out.stat().st_size > 0)


# ──────────────────────────────────────────────
# DB 记录操作 (fileUpload_file)
# ──────────────────────────────────────────────

def create_file_record(db: Session, user_id: int, stored_name: str) -> FileRecord:
    record = FileRecord(user_id=user_id, file=stored_name, upload_method='upload', created_at=datetime.now())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_file_by_id(db: Session, file_id: int) -> FileRecord | None:
    return db.query(FileRecord).filter(FileRecord.id == file_id).first()


def list_user_files(db: Session, user_id: int) -> list[FileRecord]:
    return (
        db.query(FileRecord)
        .filter(FileRecord.user_id == user_id)
        .order_by(FileRecord.id.desc())
        .all()
    )


def delete_file_record(db: Session, file_id: int, user_id: int | None = None) -> FileRecord | None:
    """删除记录 (user_id 非空时仅允许删除本人文件), 返回被删记录"""
    q = db.query(FileRecord).filter(FileRecord.id == file_id)
    if user_id is not None:
        q = q.filter(FileRecord.user_id == user_id)
    record = q.first()
    if record is None:
        return None
    db.delete(record)
    db.commit()
    return record

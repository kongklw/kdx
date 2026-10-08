"""文件上传路由 (Django fileUpload 应用迁移; URL 路径与老 /file/ 前缀一致)

端点清单 (10 个):
- POST   /file/upload           上传文件 (鉴权)
- GET    /file/list             当前用户文件列表 (新增端点, 支撑上传→列表→下载→删除全链路)
- GET    /file/r                按 key 流式返回/重定向文件 (无鉴权, 与老系统一致)
- GET    /file/r/{file_id}      按记录 id 返回文件 (无鉴权)
- GET    /file/img              图片最佳格式 (avif/webp/jpg) 协商返回 (无鉴权)
- POST   /file/presign/init     MinIO 直传预签名初始化 (鉴权)
- POST   /file/presign/complete 直传完成确认 (鉴权)
- GET    /file/presign/url      获取下载预签名 URL (鉴权)
- DELETE /file/{file_id}        删除文件记录与磁盘文件 (新增端点, 仅本人)
- GET    /media/{file_path}     静态文件服务 (对应 Django static() 挂载的 MEDIA_ROOT)

说明: DRF Response 默认 HTTP 200, 业务状态码放 body 的 code 字段;
需要真 HTTP 状态码的分支 (404/500 等) 与老 views 显式传 status 的行为保持一致。
"""

import re
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.database import get_db
from ..models.upload import MediaAsset
from ..schemas.upload import PresignCompleteRequest, PresignInitRequest
from ..services import upload_service as us
from .deps import require_user_id

_SAFE_KEY_RE = re.compile(r'^[a-zA-Z0-9/_\-.]+$')
_WIDTH_RE = re.compile(r'_w(\d+)$')


def create_file_upload_router(settings: Settings):
    router = APIRouter(tags=["file-upload"])

    # ── 上传 (对应 Django CommonFileUpload) ──────────────────
    @router.post("/file/upload")
    async def upload_file(request: Request, file: UploadFile = File(None), db: Session = Depends(get_db)):
        user_id = require_user_id(request, settings)
        if file is None or not (file.filename or '').strip():
            return JSONResponse({'code': 400, 'msg': 'No file uploaded', 'data': None})

        content = await file.read()
        stored_name = us.build_stored_name(file.filename)
        us.save_local_file(settings.media_root, stored_name, content)
        record = us.create_file_record(db, user_id, stored_name)

        # url 与 Django FileField.url 一致: MEDIA_URL(/media/) + name
        return JSONResponse({
            'code': 200,
            'data': {'id': record.id, 'name': stored_name, 'url': f'/media/{stored_name}'},
            'msg': 'ok',
        })

    # ── 文件列表 (新增端点) ──────────────────────────────────
    @router.get("/file/list")
    async def list_files(request: Request, db: Session = Depends(get_db)):
        user_id = require_user_id(request, settings)
        records = us.list_user_files(db, user_id)
        return JSONResponse({
            'code': 200,
            'msg': 'ok',
            'data': [
                {
                    'id': r.id,
                    'name': r.file,
                    'url': f'/media/{r.file}' if r.file else None,
                    'upload_method': r.upload_method,
                    'created_at': str(r.created_at),
                }
                for r in records
            ],
        })

    # ── 文件重定向/下载 (对应 Django FileRedirectView, 无鉴权) ──
    @router.get("/file/r")
    @router.get("/file/r/{file_id}")
    async def file_redirect(request: Request, file_id: int = None, db: Session = Depends(get_db)):
        key = None
        if file_id is not None:
            record = us.get_file_by_id(db, file_id)
            if not record or not record.file:
                return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)
            key = record.file
        else:
            key = (request.query_params.get('key') or '').strip() or None

        if not key:
            return JSONResponse({'code': 400, 'msg': 'key required', 'data': None}, status_code=400)
        if '..' in key:
            return JSONResponse({'code': 400, 'msg': 'invalid key', 'data': None}, status_code=400)

        # 本地磁盘优先: MEDIA_ROOT 下存在则直接流式返回 (本地模式写入的文件)
        path = us.resolve_local_path(settings.media_root, key)
        if path is not None and path.is_file():
            return FileResponse(path, media_type=us.guess_content_type(key))

        if settings.use_s3_media:
            if not (settings.minio_bucket_name and settings.minio_endpoint_url
                    and settings.minio_access_key and settings.minio_secret_key):
                return JSONResponse({'code': 500, 'msg': 'S3 bucket not configured', 'data': None}, status_code=500)

            # baby_album 视频封面特例: poster 不存在时用 ffmpeg 从 src 视频抽帧生成 (与老逻辑一致)
            src = (request.query_params.get('src') or '').strip()
            if src:
                src = unquote(src)
                if (key.startswith('baby_album/posters/') and key.lower().endswith('.jpg')
                        and _SAFE_KEY_RE.match(src) and '..' not in src and us.ffmpeg_available()):
                    try:
                        us.ensure_video_poster(settings, src, key)
                    except Exception:
                        pass

            try:
                expires_in = int(request.query_params.get('expires_in', 600) or 600)
                url = us.presign_s3_url(
                    'GET', endpoint=settings.minio_endpoint_url,
                    bucket=settings.minio_bucket_name, key=key,
                    access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
                    region=settings.minio_region_name, expires=expires_in,
                )
            except Exception as e:
                return JSONResponse({'code': 500, 'msg': str(e), 'data': None}, status_code=500)

            url = us.to_public_url(url, settings)
            # 预签名 URL 有过期时间, 禁止浏览器缓存重定向 (与老逻辑一致)
            resp = RedirectResponse(url, status_code=302)
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp

        return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)

    # ── 图片最佳格式协商 (对应 Django ImageBestRedirectView, 无鉴权) ──
    @router.get("/file/img")
    async def image_best_redirect(request: Request, db: Session = Depends(get_db)):
        base = (request.query_params.get('base') or '').strip()
        if not base or not _SAFE_KEY_RE.match(base) or '..' in base:
            return JSONResponse({'code': 400, 'msg': 'base required', 'data': None}, status_code=400)

        src = (request.query_params.get('src') or '').strip()
        if src:
            src = unquote(src)
            if not _SAFE_KEY_RE.match(src) or '..' in src:
                return JSONResponse({'code': 400, 'msg': 'invalid src', 'data': None}, status_code=400)

        # 按 Accept 协商候选格式, 顺序与老逻辑一致: avif → webp → jpg
        accept = (request.headers.get('Accept') or '').lower()
        candidates = []
        if 'image/avif' in accept:
            candidates.append(f'{base}.avif')
        if 'image/webp' in accept:
            candidates.append(f'{base}.webp')
        candidates.append(f'{base}.jpg')

        m = _WIDTH_RE.search(base)
        width = int(m.group(1)) if m else 400

        # ① 本地候选已存在 → 重定向到 /file/r (本地模式写入的变体)
        for key in candidates:
            p = us.resolve_local_path(settings.media_root, key)
            if p is not None and p.is_file():
                return RedirectResponse(f'/file/r?key={key}', status_code=302)

        # ② 本地有原图 src → 本地生成 webp/avif/jpg 变体 (PIL, 与老逻辑一致)
        src_path = us.resolve_local_path(settings.media_root, src) if src else None
        if src_path is not None and src_path.is_file():
            try:
                variants = us.make_image_variants(src_path.read_bytes(), width)
            except Exception:
                return JSONResponse({'code': 500, 'msg': 'image processing failed', 'data': None}, status_code=500)
            for fmt, data in variants.items():
                if data:
                    us.save_local_file(settings.media_root, f'{base}.{fmt}', data)
            for key in candidates:
                p = us.resolve_local_path(settings.media_root, key)
                if p is not None and p.is_file():
                    return RedirectResponse(f'/file/r?key={key}', status_code=302)
            return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)

        # ③ S3 模式: 本地无副本时走 MinIO (候选对象存在 → 重定向; 否则从 src 生成变体上传)
        if settings.use_s3_media:
            if not (settings.minio_bucket_name and settings.minio_endpoint_url
                    and settings.minio_access_key and settings.minio_secret_key):
                return JSONResponse({'code': 500, 'msg': 'S3 bucket not configured', 'data': None}, status_code=500)

            for key in candidates:
                try:
                    us.s3_head_object(settings, settings.minio_bucket_name, key)
                except Exception:
                    continue
                url = us.presign_s3_url(
                    'GET', endpoint=settings.minio_endpoint_url,
                    bucket=settings.minio_bucket_name, key=key,
                    access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
                    region=settings.minio_region_name,
                    expires=int(request.query_params.get('expires_in', 600) or 600),
                )
                resp = RedirectResponse(us.to_public_url(url, settings), status_code=302)
                resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                resp.headers['Pragma'] = 'no-cache'
                resp.headers['Expires'] = '0'
                return resp

            # 候选不存在 → 从 src 原图生成变体并上传
            if src:
                import os
                import tempfile
                tmp_in_fd, tmp_in = tempfile.mkstemp(suffix=os.path.splitext(src)[1] or '.jpg')
                os.close(tmp_in_fd)
                try:
                    try:
                        us.s3_download_file(settings, settings.minio_bucket_name, src, tmp_in)
                    except Exception:
                        return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)
                    try:
                        with open(tmp_in, 'rb') as f:
                            variants = us.make_image_variants(f.read(), width)
                    except Exception:
                        return JSONResponse({'code': 500, 'msg': 'image processing failed', 'data': None}, status_code=500)

                    content_types = {'webp': 'image/webp', 'avif': 'image/avif', 'jpg': 'image/jpeg'}
                    for fmt, data in variants.items():
                        if data:
                            us.s3_upload_bytes(settings, settings.minio_bucket_name,
                                               f'{base}.{fmt}', data, content_types[fmt])
                finally:
                    try:
                        if os.path.exists(tmp_in):
                            os.remove(tmp_in)
                    except Exception:
                        pass

                for key in candidates:
                    try:
                        us.s3_head_object(settings, settings.minio_bucket_name, key)
                    except Exception:
                        continue
                    url = us.presign_s3_url(
                        'GET', endpoint=settings.minio_endpoint_url,
                        bucket=settings.minio_bucket_name, key=key,
                        access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
                        region=settings.minio_region_name,
                        expires=int(request.query_params.get('expires_in', 600) or 600),
                    )
                    return RedirectResponse(us.to_public_url(url, settings), status_code=302)

            return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)

        return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)

    # ── MinIO 直传: 初始化 (对应 Django PresignInitView) ──────
    @router.post("/file/presign/init")
    async def presign_init(request: Request, body: PresignInitRequest, db: Session = Depends(get_db)):
        user_id = require_user_id(request, settings)
        if not settings.use_s3_media:
            return JSONResponse({'code': 400, 'msg': 'S3 media not enabled', 'data': None})

        purpose = (body.purpose or '').strip()
        filename = (body.filename or '').strip()
        if not purpose:
            return JSONResponse({'code': 400, 'msg': 'purpose 必填', 'data': None})
        if not filename:
            return JSONResponse({'code': 400, 'msg': 'filename 必填', 'data': None})

        bucket = settings.minio_bucket_name
        endpoint = settings.minio_endpoint_url
        if not (bucket and endpoint and settings.minio_access_key and settings.minio_secret_key):
            return JSONResponse({'code': 500, 'msg': 'S3 configuration incomplete', 'data': None})

        object_key = us.make_object_key(purpose, filename)
        now = datetime.now()
        asset = MediaAsset(
            user_id=user_id,
            bucket=bucket,
            object_key=object_key,
            original_name=filename[:255],
            content_type=(body.content_type or '').strip()[:255] or None,
            size_bytes=body.size if isinstance(body.size, int) else None,
            is_video=body.is_video,
            purpose=purpose[:64],
            status='init',
            created_at=now,
            updated_at=now,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        upload_url = us.presign_s3_url(
            'PUT', endpoint=endpoint, bucket=bucket, key=object_key,
            access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
            region=settings.minio_region_name,
            expires=int(body.expires_in or 600),
            content_type=(body.content_type or '').strip() or None,
        )
        # 内部地址 → 外部地址 (Nginx /minio/ 代理兜底), 与老逻辑一致
        upload_url = us.to_nginx_proxy_url(upload_url, settings)

        return JSONResponse({
            'code': 200,
            'msg': 'ok',
            'data': {
                'asset_id': asset.id,
                'bucket': bucket,
                'object_key': object_key,
                'upload_url': upload_url,
                'headers': {'Content-Type': body.content_type} if body.content_type else {},
            },
        })

    # ── MinIO 直传: 完成确认 (对应 Django PresignCompleteView) ──
    @router.post("/file/presign/complete")
    async def presign_complete(request: Request, body: PresignCompleteRequest, db: Session = Depends(get_db)):
        user_id = require_user_id(request, settings)
        if not settings.use_s3_media:
            return JSONResponse({'code': 400, 'msg': 'S3 media not enabled', 'data': None})
        if not body.asset_id:
            return JSONResponse({'code': 400, 'msg': 'asset_id 必填', 'data': None})

        asset = (
            db.query(MediaAsset)
            .filter(MediaAsset.id == body.asset_id, MediaAsset.user_id == user_id)
            .first()
        )
        if not asset:
            return JSONResponse({'code': 404, 'msg': 'asset 不存在', 'data': None})

        try:
            head = us.s3_head_object(settings, asset.bucket, asset.object_key)
        except Exception:
            return JSONResponse({'code': 400, 'msg': '对象未找到或不可访问', 'data': None})

        asset.etag = (head.get('etag') or '').strip('"') or asset.etag
        try:
            asset.size_bytes = int(head.get('size')) if head.get('size') else asset.size_bytes
        except (TypeError, ValueError):
            pass
        asset.content_type = head.get('content_type') or asset.content_type
        asset.status = 'uploaded'
        asset.updated_at = datetime.now()
        db.commit()

        return JSONResponse({
            'code': 200,
            'msg': 'ok',
            'data': {'asset_id': asset.id, 'bucket': asset.bucket, 'object_key': asset.object_key},
        })

    # ── MinIO 直传: 获取下载 URL (对应 Django PresignGetUrlView) ──
    @router.get("/file/presign/url")
    async def presign_url(request: Request, db: Session = Depends(get_db)):
        user_id = require_user_id(request, settings)
        if not settings.use_s3_media:
            return JSONResponse({'code': 400, 'msg': 'S3 media not enabled', 'data': None})

        asset_id = request.query_params.get('asset_id')
        if not asset_id:
            return JSONResponse({'code': 400, 'msg': 'asset_id 必填', 'data': None})

        asset = (
            db.query(MediaAsset)
            .filter(MediaAsset.id == asset_id, MediaAsset.user_id == user_id)
            .first()
        )
        if not asset:
            return JSONResponse({'code': 404, 'msg': 'asset 不存在', 'data': None})

        url = us.presign_s3_url(
            'GET', endpoint=settings.minio_endpoint_url, bucket=asset.bucket, key=asset.object_key,
            access_key=settings.minio_access_key, secret_key=settings.minio_secret_key,
            region=settings.minio_region_name,
            expires=int(request.query_params.get('expires_in', 600) or 600),
        )
        return JSONResponse({'code': 200, 'msg': 'ok', 'data': {'url': us.to_public_url(url, settings)}})

    # ── 删除文件 (新增端点, 仅本人) ──────────────────────────
    @router.delete("/file/{file_id}")
    async def delete_file(file_id: int, request: Request, db: Session = Depends(get_db)):
        user_id = require_user_id(request, settings)
        deleted = us.delete_file_record(db, file_id, user_id=user_id)
        if deleted is None:
            return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None})
        # 同时删除本地磁盘文件 (存在才删; S3 模式下对象由 MinIO 生命周期管理, 不在此删)
        if deleted.file:
            us.delete_local_file(settings.media_root, deleted.file)
        return JSONResponse({'code': 200, 'msg': 'ok', 'data': {'id': deleted.id}})

    # ── 静态文件服务 (对应 Django static() 挂载的 /media/) ────
    @router.get("/media/{file_path:path}")
    async def media_files(file_path: str):
        path = us.resolve_local_path(settings.media_root, file_path)
        if path is None or not path.is_file():
            return JSONResponse({'code': 404, 'msg': 'file not found', 'data': None}, status_code=404)
        return FileResponse(path, media_type=us.guess_content_type(file_path))

    return router

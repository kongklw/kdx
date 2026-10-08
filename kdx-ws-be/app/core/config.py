import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 模块级加载 .env: 保证任意 import 顺序下 (如 core/database.py 在模块级
# 调用 get_settings() 创建 engine) 环境变量均已就位, 避免绑定默认 127.0.0.1 DSN
_BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(_BASE_DIR / ".env")


def load_env(default_env_path) -> None:
    from dotenv import load_dotenv as _load
    _load(default_env_path)


@dataclass(frozen=True)
class Settings:
    secret_key: str
    jwt_algorithm: str
    redis_url: str
    mysql_dsn: str
    allow_anon_ws: bool
    # 文件存储根目录 (对应 Django MEDIA_ROOT, 即 kdx-be/media/), 可用 MEDIA_ROOT 环境变量覆盖
    media_root: str = ""
    # MinIO/S3 直传配置 (与老 Django .env 同名变量; 未启用时 presign 端点返回 S3 media not enabled)
    use_s3_media: bool = False
    minio_endpoint_url: str = ""
    minio_public_endpoint_url: str = ""
    minio_bucket_name: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_region_name: str = "us-east-1"
    minio_verify_ssl: bool = True


def get_settings() -> Settings:
    secret_key = os.getenv("SECRET_KEY") or ""
    jwt_algorithm = os.getenv("JWT_ALGORITHM") or "HS256"

    redis_host = os.getenv("REDIS_HOST") or "127.0.0.1"
    redis_port = os.getenv("REDIS_PORT") or "6379"
    redis_db = os.getenv("REDIS_CACHE_DB") or "0"
    redis_password = os.getenv("REDIS_PASSWORD") or ""
    if redis_password:
        redis_url = f"redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}"
    else:
        redis_url = f"redis://{redis_host}:{redis_port}/{redis_db}"

    mysql_user = os.getenv("MYSQL_USER") or ""
    mysql_password = os.getenv("MYSQL_PASSWORD") or ""
    mysql_host = os.getenv("DB_HOST") or "127.0.0.1"
    mysql_port = os.getenv("DB_PORT") or "3306"
    mysql_db = os.getenv("MYSQL_DATABASE") or ""
    # user/password 必须 URL 编码, 否则密码含 @ 等特殊字符会破坏 DSN 解析
    from urllib.parse import quote_plus
    mysql_dsn = (
        f"mysql+pymysql://{quote_plus(mysql_user)}:{quote_plus(mysql_password)}"
        f"@{mysql_host}:{mysql_port}/{mysql_db}"
    )

    allow_anon_ws = (os.getenv("VOICE_WS_ALLOW_ANON") or "").lower() in {"1", "true", "yes"}

    # 文件存储: 默认指向老 Django 项目 MEDIA_ROOT 同一磁盘目录 (kdx-be/media/)
    media_root = os.getenv("MEDIA_ROOT") or str(_BASE_DIR.parent / "kdx-be" / "media")

    # MinIO/S3 配置 (变量名与老 Django settings 保持一致)
    use_s3_media = (os.getenv("USE_S3_MEDIA") or "").lower() in {"1", "true", "yes"}
    minio_endpoint_url = os.getenv("MINIO_ENDPOINT_URL") or ""
    minio_public_endpoint_url = os.getenv("MINIO_PUBLIC_ENDPOINT_URL") or minio_endpoint_url

    return Settings(
        secret_key=secret_key,
        jwt_algorithm=jwt_algorithm,
        redis_url=redis_url,
        mysql_dsn=mysql_dsn,
        allow_anon_ws=allow_anon_ws,
        media_root=media_root,
        use_s3_media=use_s3_media,
        minio_endpoint_url=minio_endpoint_url,
        minio_public_endpoint_url=minio_public_endpoint_url,
        minio_bucket_name=os.getenv("MINIO_BUCKET_NAME") or "",
        minio_access_key=os.getenv("MINIO_ACCESS_KEY") or "",
        minio_secret_key=os.getenv("MINIO_SECRET_KEY") or "",
        minio_region_name=os.getenv("MINIO_REGION_NAME") or "us-east-1",
        minio_verify_ssl=(os.getenv("MINIO_VERIFY_SSL") or "true").lower() in {"1", "true", "yes"},
    )

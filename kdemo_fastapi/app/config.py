import os
from dataclasses import dataclass
from pathlib import Path


def load_env(default_env_path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(default_env_path)


@dataclass(frozen=True)
class Settings:
    secret_key: str
    jwt_algorithm: str
    redis_url: str
    mysql_dsn: str
    allow_anon_ws: bool


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
    mysql_dsn = f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_db}"

    allow_anon_ws = (os.getenv("VOICE_WS_ALLOW_ANON") or "").lower() in {"1", "true", "yes"}

    return Settings(
        secret_key=secret_key,
        jwt_algorithm=jwt_algorithm,
        redis_url=redis_url,
        mysql_dsn=mysql_dsn,
        allow_anon_ws=allow_anon_ws,
    )


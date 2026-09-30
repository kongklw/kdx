# kdx-ws-be 镜像
# 说明: 本机 Docker 未安装 buildx, 只能用 legacy builder; legacy builder 在 COPY
# 跨阶段大目录(如 ~1.5GB 的 .venv)时会报 "archive/tar: invalid tar header"。
# 因此采用单阶段构建: 用 uv 在镜像内直接同步依赖到 /app/.venv, 再以该 venv 启动。
# 生产环境 compose 仍会用卷挂载覆盖 /app/app, 镜像本身也自带源码可独立运行。

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

# 阿里云镜像加速 apt + 安装运行时系统依赖
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
        unzip \
        libgl1-mesa-glx \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libx11-6 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ORT_DISABLE_CPU_OPTIMIZATION=1 \
    ONNXRUNTIME_DISABLE_OPTIMIZATION=1 \
    INSIGHTFACE_HOME=/home/appuser/.insightface \
    TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface \
    # uv: 用 copy 模式(跨文件系统安全)、用系统 Python 3.12、固定 venv 路径
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    # 让 venv 里的 uvicorn / python 直接可用
    PATH="/app/.venv/bin:$PATH"

RUN useradd -m -u 1000 appuser

WORKDIR /app

# 仅拷贝依赖描述文件, 最大化利用 Docker 层缓存(改动 app/ 不会重装依赖)
# 不使用 uv.lock: 每次构建按 pyproject.toml 的约束实时解析,
# 避免锁文件里固化的镜像源 URL 失效(如镜像源 403)导致构建失败
COPY ./kdx-ws-be/pyproject.toml /app/

# 安装 uv 并按 pyproject.toml 解析安装生产依赖
#   --no-dev         : 跳过开发依赖
#   --no-install-project : 只装依赖, 不构建项目本身(运行代码 app/ 由下方 COPY 提供)
#   UV_CACHE_DIR 指向临时目录并在安装后清理, 避免缓存撑大镜像
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/ && \
    UV_CACHE_DIR=/tmp/uv-cache uv sync --no-dev --no-install-project && \
    rm -rf /tmp/uv-cache /root/.cache/huggingface

# 准备运行时目录与权限
RUN mkdir -p /home/appuser/.insightface/models /home/appuser/.cache/huggingface && \
    chown -R appuser:appuser /home/appuser /app

USER appuser

# 内置源码保证镜像可独立运行; 生产环境 compose 会用卷挂载覆盖 ./app
COPY --chown=appuser:appuser ./kdx-ws-be/app /app/app
COPY --chown=appuser:appuser ./kdx-ws-be/scripts /app/scripts

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

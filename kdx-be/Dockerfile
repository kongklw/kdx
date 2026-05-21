# 建立 python 3.12环境
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

RUN echo "Hello, Docker!"

# 替换软件源为阿里云
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 安装系统依赖 (mysqlclient 需要)
RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    netcat-openbsd \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# image author
MAINTAINER kdemo

# 设置 python 环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 禁用 ONNX Runtime CPU 优化（兼容更多 CPU 型号）
ENV ORT_DISABLE_CPU_OPTIMIZATION 1
ENV ONNXRUNTIME_DISABLE_OPTIMIZATION 1

# 容器内创建 myproject 文件夹
ENV APP_HOME=/home/kdx-be
RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

# ============================================
# 使用 uv 管理依赖（优化：先复制配置文件，利用 Docker 缓存）
# ============================================

# 先复制 pyproject.toml（变化频率低）
COPY pyproject.toml .

# 安装 uv
RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install uv -i https://mirrors.aliyun.com/pypi/simple/

# 配置 uv 使用国内镜像
RUN uv config set registry.index-url https://mirrors.aliyun.com/pypi/simple/

# 使用 uv 安装依赖（可缓存）
RUN uv sync

# ============================================
# 预下载 InsightFace 模型（在构建阶段完成）
# ============================================

# 创建 InsightFace 模型目录并设置权限
RUN mkdir -p /root/.insightface && chmod -R 755 /root/.insightface

# 复制模型下载脚本
COPY scripts/download_insightface_models.py /tmp/

# 运行模型预下载脚本
RUN uv run python /tmp/download_insightface_models.py

# ============================================
# 最后复制代码（变化频率高）
# ============================================

# 将当前目录加入到工作目录中（. 表示当前目录）
ADD . $APP_HOME

RUN uv run uwsgi --version

# 创建日志目录
RUN mkdir -p /home/kdx-be/logs

# 添加健康检查
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8000/ || exit 1

# 使用 uwsgi 启动服务，并通过 tail 保持容器前台运行
CMD ["sh", "-c", "uv run uwsgi --ini /home/kdx-be/uwsgi.ini && tail -f /home/kdx-be/logs/uwsgi.log"]
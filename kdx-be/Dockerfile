# 使用华为云 Python 镜像（阿里云ECS环境）
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

# 设置超时环境变量
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_CONNECT_TIMEOUT=60

# 替换软件源为阿里云
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    netcat-openbsd \
    ffmpeg \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 设置 python 环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 禁用 ONNX Runtime 和 OpenCV 的 CPU 优化（兼容更多 CPU 型号）
ENV ORT_DISABLE_CPU_OPTIMIZATION 1
ENV ONNXRUNTIME_DISABLE_OPTIMIZATION 1
ENV OMP_NUM_THREADS=1
ENV OPENCV_DNN_USE_OPENCL=0

# 容器内创建 myproject 文件夹
ENV APP_HOME=/home/kdx-be
RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

# 先复制 pyproject.toml（变化频率低）
COPY pyproject.toml .

# 使用 pip 直接安装依赖（更稳定）
RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install -e . -i https://mirrors.aliyun.com/pypi/simple/ --no-cache-dir

# ============================================
# 预下载 InsightFace 模型（在构建阶段完成）
# ============================================

# 创建 InsightFace 模型目录并设置权限
RUN mkdir -p /root/.insightface && chmod -R 755 /root/.insightface

# 复制模型下载脚本
COPY scripts/download_insightface_models.py /tmp/

# 运行模型预下载脚本（GitHub Actions 网络可以访问 GitHub）
RUN python /tmp/download_insightface_models.py

# 将当前目录加入到工作目录中
ADD . $APP_HOME

# 创建日志目录
RUN mkdir -p /home/kdx-be/logs

# 添加健康检查
HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:8000/ || exit 1

# 使用 uwsgi 启动服务
CMD ["uwsgi", "--ini", "/home/kdx-be/uwsgi.ini"]
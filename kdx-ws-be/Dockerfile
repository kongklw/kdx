# 使用 Python 3.12 基础镜像
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

# 配置阿里云镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 安装系统依赖（OpenCV 需要）
RUN apt-get update && apt-get install -y \
    unzip \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libx11-6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_CONNECT_TIMEOUT=60

# 禁用 ONNX Runtime CPU 优化（兼容更多 CPU 型号）
ENV ORT_DISABLE_CPU_OPTIMIZATION 1
ENV ONNXRUNTIME_DISABLE_OPTIMIZATION 1

# 工作目录
WORKDIR /app

# 复制项目配置文件
COPY ./kdx-ws-be/requirements.txt /app/requirements.txt

# 安装依赖（使用 pip）
RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --no-cache-dir

# 复制应用代码和脚本
COPY ./kdx-ws-be/app /app/app
COPY ./kdx-ws-be/scripts /app/scripts

# 创建 InsightFace 模型目录
RUN mkdir -p /root/.insightface/models

# 从 kdx-be 目录复制本地模型（与 kdx-be 保持一致）
COPY ./kdx-be/buffalo_l.zip /tmp/buffalo_l.zip
RUN unzip -q /tmp/buffalo_l.zip -d /root/.insightface/models/ && \
    rm /tmp/buffalo_l.zip && \
    chmod -R 755 /root/.insightface

# 暴露端口
EXPOSE 8002

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
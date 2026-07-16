# 第一阶段：构建阶段
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim AS builder

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

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

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_CONNECT_TIMEOUT=60
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY ./kdx-ws-be/requirements.txt /app/requirements.txt

RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --break-system-packages && \
    rm -rf /root/.cache/huggingface/hub

RUN useradd -m -u 1000 appuser

# 第二阶段：最终阶段
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim AS final

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libx11-6 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV ORT_DISABLE_CPU_OPTIMIZATION 1
ENV ONNXRUNTIME_DISABLE_OPTIMIZATION 1
ENV INSIGHTFACE_HOME=/home/appuser/.insightface
ENV TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

RUN mkdir -p /home/appuser/.insightface/models && \
    mkdir -p /home/appuser/.cache/huggingface && \
    chown -R appuser:appuser /home/appuser

USER appuser

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
# 使用 Python 3.12 基础镜像
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

RUN echo "Hello, Docker!"
# 配置阿里云镜像源
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 禁用 ONNX Runtime CPU 优化（兼容更多 CPU 型号）
ENV ORT_DISABLE_CPU_OPTIMIZATION 1
ENV ONNXRUNTIME_DISABLE_OPTIMIZATION 1

# 工作目录
WORKDIR /app

# 复制项目配置文件
COPY ./pyproject.toml /app/pyproject.toml

# 安装依赖（使用 uv）
RUN pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install uv -i https://mirrors.aliyun.com/pypi/simple/ && \
    uv config set registry.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    uv sync

# 复制应用代码和脚本
COPY ./app /app/app
COPY ./scripts /app/scripts

# 创建 InsightFace 模型目录并设置权限
RUN mkdir -p /root/.insightface && chmod -R 755 /root/.insightface

# 在构建阶段预下载 InsightFace 模型
RUN python /app/scripts/download_insightface_models.py

# 暴露端口
EXPOSE 8002

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

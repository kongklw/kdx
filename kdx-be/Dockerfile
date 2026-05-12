# 建立 python 3.12环境
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

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

# 可选：设置镜像源为国内
COPY pip.conf /root/.pip/pip.conf

# 容器内创建 myproject 文件夹
ENV APP_HOME=/home/kdx-be
RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

# ============================================
# 优化：先复制 requirements.txt，利用 Docker 缓存
# 只要 requirements.txt 不变，pip install 会使用缓存
# ============================================

# 先复制 requirements.txt（变化频率低）
COPY requirements.txt .

# 更新 pip 版本
RUN /usr/local/bin/python -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/

# 安装项目依赖（可缓存）
RUN pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# ============================================
# 最后复制代码（变化频率高）
# ============================================

# 将当前目录加入到工作目录中（. 表示当前目录）
ADD . $APP_HOME

RUN uwsgi --version

# 创建日志目录
RUN mkdir -p /home/kdx-be/logs

# 直接使用 uwsgi 启动服务
CMD ["uwsgi", "--ini", "/home/kdx-be/uwsgi.ini"]

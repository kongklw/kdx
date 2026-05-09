#!/bin/bash
set -e

echo "=== KDX 项目初始化脚本 ==="

# 1. 安装必要依赖
echo "=== 安装依赖 ==="
yum update -y
yum install -y git docker docker-compose

# 2. 启动 Docker
systemctl enable docker
systemctl start docker

# 3. 创建项目目录
echo "=== 创建目录结构 ==="
mkdir -p /data/kdx
cd /data/kdx

# 4. 克隆仓库
echo "=== 克隆代码仓库 ==="
git clone https://github.com/yourname/kdx.git .

# 5. 设置环境变量
echo "=== 配置环境变量 ==="
cat > /data/kdx/.env << 'EOF'
DB_PASSWORD=your-db-password
DB_ROOT_PASSWORD=your-root-password
EOF

# 6. 初始化服务
echo "=== 启动服务 ==="
docker-compose up -d

echo "=== 等待服务启动 ==="
sleep 30

# 7. 数据库迁移
echo "=== 数据库迁移 ==="
docker-compose exec -T kdx-be python manage.py migrate --noinput
docker-compose exec -T kdx-be python manage.py collectstatic --noinput

echo "✅ KDX 项目初始化完成！"
echo "项目地址: http://<your-server-ip>"
echo "管理后台: http://<your-server-ip>/admin"
#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ ! -f "${PROJECT_PATH}/.env" ]; then
    echo -e "${RED}错误: .env 文件不存在${NC}"
    exit 1
fi

source "${PROJECT_PATH}/.env"

if [ -z "$ACR_REGISTRY" ] || [ -z "$ACR_NAMESPACE" ]; then
    echo -e "${RED}错误: .env 文件中缺少必要的ACR配置${NC}"
    exit 1
fi

cd "${PROJECT_PATH}"

echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE}          KDX 部署脚本 (ACR模式)            ${NC}"
echo -e "${BLUE}=============================================${NC}"
echo ""

echo -e "${YELLOW}步骤 1/3: 重启服务...${NC}"

echo -e "${BLUE}重启后端服务...${NC}"
docker compose restart web

echo -e "${BLUE}重启FastAPI服务...${NC}"
docker compose restart kdx_ws

echo -e "${BLUE}重启Nginx服务...${NC}"
docker compose restart nginx

echo -e "${GREEN}服务重启完成！${NC}"
echo ""

echo -e "${YELLOW}步骤 2/3: 执行数据库迁移...${NC}"
docker compose exec -T web python manage.py migrate --noinput 2>/dev/null || echo "数据库迁移已跳过"
echo -e "${GREEN}数据库迁移完成！${NC}"
echo ""

echo -e "${YELLOW}步骤 3/3: 收集静态文件...${NC}"
docker compose exec -T web python manage.py collectstatic --noinput 2>/dev/null || echo "静态文件收集已跳过"
echo -e "${GREEN}静态文件收集完成！${NC}"
echo ""

echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN}          部署完成！                         ${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""

echo -e "${YELLOW}服务状态:${NC}"
docker compose ps
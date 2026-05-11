#!/bin/bash

# ==============================================================================
# KDX 项目一键部署脚本
# 支持按需部署后端、前端、FastAPI、Nginx等模块
# ==============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目路径
PROJECT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DOCKER_COMPOSE="docker-compose"

# 检查 docker-compose 命令
if ! command -v docker-compose &> /dev/null; then
    if command -v docker &> /dev/null && docker compose version &> /dev/null; then
        DOCKER_COMPOSE="docker compose"
    else
        echo -e "${RED}错误: 未找到 docker-compose 或 docker compose${NC}"
        exit 1
    fi
fi

# 检查是否在项目根目录
if [ ! -f "${PROJECT_PATH}/docker-compose.yaml" ]; then
    echo -e "${RED}错误: 请在项目根目录运行此脚本${NC}"
    exit 1
fi

# 显示帮助信息
show_help() {
    echo -e "${BLUE}=============================================${NC}"
    echo -e "${BLUE}          KDX 项目一键部署脚本               ${NC}"
    echo -e "${BLUE}=============================================${NC}"
    echo ""
    echo -e "${YELLOW}使用方法:${NC}"
    echo "  $0 [选项] [模块...]"
    echo ""
    echo -e "${YELLOW}选项:${NC}"
    echo "  -h, --help          显示帮助信息"
    echo "  -s, --start         启动服务（默认）"
    echo "  -d, --down          停止并移除容器"
    echo "  -r, --restart       重启服务"
    echo "  -b, --build         构建镜像（不启动）"
    echo "  -u, --update        拉取最新代码并部署"
    echo "  -l, --logs          查看日志"
    echo "  -c, --clean         清理停止的容器和无用镜像"
    echo ""
    echo -e "${YELLOW}模块（可选，不指定则部署全部）:${NC}"
    echo "  all          部署所有服务（默认）"
    echo "  backend      仅部署后端 (Django)"
    echo "  frontend     仅部署前端 (Vue)"
    echo "  fastapi      仅部署 FastAPI 服务"
    echo "  nginx        仅部署 Nginx"
    echo "  db           仅部署数据库 (MySQL + Redis)"
    echo "  voice_ws     仅部署语音 WebSocket 服务"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo "  $0                    # 启动所有服务"
    echo "  $0 -b                 # 构建所有镜像"
    echo "  $0 backend frontend   # 仅启动后端和前端"
    echo "  $0 -u backend         # 更新代码并部署后端"
    echo "  $0 -r nginx           # 重启 Nginx"
    echo "  $0 -l web             # 查看 web 容器日志"
    echo ""
}

# 构建前端
build_frontend() {
    echo -e "${YELLOW}=== 构建前端项目 ===${NC}"
    cd "${PROJECT_PATH}/kdx-fe"

    if [ ! -d "node_modules" ]; then
        echo -e "${BLUE}安装依赖...${NC}"
        npm ci --only=production
    fi

    echo -e "${BLUE}执行构建...${NC}"
    npm run build

    cd "${PROJECT_PATH}"
}

# 部署后端
deploy_backend() {
    echo -e "${YELLOW}=== 部署后端服务 ===${NC}"

    # 构建并启动后端容器
    ${DOCKER_COMPOSE} up -d --build --no-deps web

    # 等待容器启动
    sleep 5

    # 执行数据库迁移
    echo -e "${BLUE}执行数据库迁移...${NC}"
    ${DOCKER_COMPOSE} exec -T kdx-be python manage.py migrate --noinput

    # 收集静态文件
    echo -e "${BLUE}收集静态文件...${NC}"
    ${DOCKER_COMPOSE} exec -T kdx-be python manage.py collectstatic --noinput

    echo -e "${GREEN}后端部署完成！${NC}"
}

# 部署 FastAPI
deploy_fastapi() {
    echo -e "${YELLOW}=== 部署 FastAPI 服务 ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps fastapi
    echo -e "${GREEN}FastAPI 部署完成！${NC}"
}

# 部署 Nginx
deploy_nginx() {
    echo -e "${YELLOW}=== 部署 Nginx ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps nginx
    echo -e "${GREEN}Nginx 部署完成！${NC}"
}

# 部署数据库
deploy_db() {
    echo -e "${YELLOW}=== 部署数据库服务 ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps redis db
    echo -e "${GREEN}数据库服务部署完成！${NC}"
}

# 部署语音 WebSocket
deploy_voice_ws() {
    echo -e "${YELLOW}=== 部署语音 WebSocket 服务 ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps voice_ws
    echo -e "${GREEN}语音 WebSocket 部署完成！${NC}"
}

# 部署所有服务
deploy_all() {
    echo -e "${YELLOW}=== 部署所有服务 ===${NC}"

    # 先部署数据库
    deploy_db

    # 部署后端
    deploy_backend

    # 部署语音 WebSocket
    deploy_voice_ws

    # 部署 FastAPI
    deploy_fastapi

    # 构建前端
    build_frontend

    # 部署 Nginx
    deploy_nginx

    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}          所有服务部署完成！                 ${NC}"
    echo -e "${GREEN}=============================================${NC}"
}

# 拉取最新代码
pull_code() {
    echo -e "${YELLOW}=== 拉取最新代码 ===${NC}"
    git pull origin main
    echo -e "${GREEN}代码拉取完成！${NC}"
}

# 主函数
main() {
    local action="start"
    local modules=("all")

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                show_help
                exit 0
                ;;
            -s|--start)
                action="start"
                shift
                ;;
            -d|--down)
                action="down"
                shift
                ;;
            -r|--restart)
                action="restart"
                shift
                ;;
            -b|--build)
                action="build"
                shift
                ;;
            -u|--update)
                action="update"
                shift
                ;;
            -l|--logs)
                action="logs"
                shift
                ;;
            -c|--clean)
                action="clean"
                shift
                ;;
            all|backend|frontend|fastapi|nginx|db|voice_ws)
                modules=("$1")
                shift
                ;;
            *)
                echo -e "${RED}错误: 未知参数 '$1'${NC}"
                show_help
                exit 1
                ;;
        esac
    done

    # 切换到项目目录
    cd "${PROJECT_PATH}"

    # 执行操作
    case "$action" in
        start)
            case "${modules[0]}" in
                all)
                    deploy_all
                    ;;
                backend)
                    deploy_backend
                    ;;
                frontend)
                    build_frontend
                    deploy_nginx
                    ;;
                fastapi)
                    deploy_fastapi
                    ;;
                nginx)
                    deploy_nginx
                    ;;
                db)
                    deploy_db
                    ;;
                voice_ws)
                    deploy_voice_ws
                    ;;
            esac
            ;;

        down)
            echo -e "${YELLOW}=== 停止并移除容器 ===${NC}"
            ${DOCKER_COMPOSE} down
            echo -e "${GREEN}容器已停止并移除！${NC}"
            ;;

        restart)
            echo -e "${YELLOW}=== 重启服务 ===${NC}"
            case "${modules[0]}" in
                all)
                    ${DOCKER_COMPOSE} restart
                    ;;
                backend)
                    ${DOCKER_COMPOSE} restart web
                    ;;
                frontend)
                    ${DOCKER_COMPOSE} restart nginx
                    ;;
                fastapi)
                    ${DOCKER_COMPOSE} restart fastapi
                    ;;
                nginx)
                    ${DOCKER_COMPOSE} restart nginx
                    ;;
                db)
                    ${DOCKER_COMPOSE} restart redis db
                    ;;
                voice_ws)
                    ${DOCKER_COMPOSE} restart voice_ws
                    ;;
            esac
            echo -e "${GREEN}服务已重启！${NC}"
            ;;

        build)
            echo -e "${YELLOW}=== 构建镜像 ===${NC}"
            case "${modules[0]}" in
                all)
                    ${DOCKER_COMPOSE} build
                    ;;
                backend)
                    ${DOCKER_COMPOSE} build web
                    ;;
                frontend)
                    build_frontend
                    ${DOCKER_COMPOSE} build nginx
                    ;;
                fastapi)
                    ${DOCKER_COMPOSE} build fastapi
                    ;;
                nginx)
                    ${DOCKER_COMPOSE} build nginx
                    ;;
                db)
                    ${DOCKER_COMPOSE} build redis db
                    ;;
                voice_ws)
                    ${DOCKER_COMPOSE} build voice_ws
                    ;;
            esac
            echo -e "${GREEN}镜像构建完成！${NC}"
            ;;

        update)
            pull_code
            case "${modules[0]}" in
                all)
                    deploy_all
                    ;;
                backend)
                    deploy_backend
                    ;;
                frontend)
                    build_frontend
                    deploy_nginx
                    ;;
                fastapi)
                    deploy_fastapi
                    ;;
                nginx)
                    deploy_nginx
                    ;;
                db)
                    deploy_db
                    ;;
                voice_ws)
                    deploy_voice_ws
                    ;;
            esac
            ;;

        logs)
            echo -e "${YELLOW}=== 查看日志 ===${NC}"
            case "${modules[0]}" in
                all)
                    ${DOCKER_COMPOSE} logs -f
                    ;;
                backend)
                    ${DOCKER_COMPOSE} logs -f web
                    ;;
                frontend)
                    ${DOCKER_COMPOSE} logs -f nginx
                    ;;
                fastapi)
                    ${DOCKER_COMPOSE} logs -f fastapi
                    ;;
                nginx)
                    ${DOCKER_COMPOSE} logs -f nginx
                    ;;
                db)
                    ${DOCKER_COMPOSE} logs -f redis db
                    ;;
                voice_ws)
                    ${DOCKER_COMPOSE} logs -f voice_ws
                    ;;
            esac
            ;;

        clean)
            echo -e "${YELLOW}=== 清理无用资源 ===${NC}"
            echo -e "${BLUE}停止所有容器...${NC}"
            docker stop $(docker ps -aq) 2>/dev/null || true

            echo -e "${BLUE}删除停止的容器...${NC}"
            docker rm $(docker ps -aq) 2>/dev/null || true

            echo -e "${BLUE}删除无用镜像...${NC}"
            docker image prune -f

            echo -e "${BLUE}删除无用网络...${NC}"
            docker network prune -f

            echo -e "${GREEN}清理完成！${NC}"
            ;;
    esac
}

# 执行主函数
main "$@"

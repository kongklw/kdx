#!/bin/bash

# ==============================================================================
# KDX 项目一键部署脚本
# 支持按需部署，智能启动顺序，健康检查
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
MAX_WAIT=300
CHECK_INTERVAL=2

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

# 检查服务是否正在运行
is_service_running() {
    local service=$1
    ${DOCKER_COMPOSE} ps -q "$service" | grep -q .
}

# 检查容器是否健康（兼容服务名和容器名）
wait_for_container() {
    local container_name=$1
    local timeout=${2:-$MAX_WAIT}
    
    echo -e "${BLUE}等待 ${container_name} 容器就绪...${NC}"
    
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        # 尝试通过服务名获取容器 ID
        local container_id=$(${DOCKER_COMPOSE} ps -q "$container_name" 2>/dev/null)
        
        # 如果服务名方式失败，尝试通过容器名直接查找
        if [ -z "$container_id" ]; then
            container_id=$(docker ps -q --filter "name=^/${container_name}$" 2>/dev/null)
        fi
        
        if [ -n "$container_id" ]; then
            # 使用 docker inspect 检查容器状态（兼容旧版本）
            local status=$(docker inspect --format='{{.State.Status}}' "$container_id" 2>/dev/null)
            if [ "$status" = "running" ]; then
                echo -e "${GREEN}${container_name} 容器已就绪${NC}"
                return 0
            fi
        fi
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
        echo -ne "${YELLOW}.${NC}"
    done
    
    echo -e "\n${RED}错误: ${container_name} 容器启动超时${NC}"
    ${DOCKER_COMPOSE} logs "$container_name" 2>/dev/null | tail -20 || docker logs "$container_name" 2>/dev/null | tail -20
    return 1
}

# 检查端口是否就绪（用于有端口映射的服务）
wait_for_port() {
    local service=$1
    local port=$2
    local host=${3:-localhost}
    local timeout=${4:-$MAX_WAIT}
    
    echo -e "${BLUE}等待 ${service} 服务就绪...${NC}"
    
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if is_service_running "$service"; then
            if timeout 1 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
                echo -e "${GREEN}${service} 服务已就绪${NC}"
                return 0
            fi
        fi
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
        echo -ne "${YELLOW}.${NC}"
    done
    
    echo -e "\n${RED}错误: ${service} 服务启动超时${NC}"
    ${DOCKER_COMPOSE} logs "$service" | tail -20
    return 1
}

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
    echo "  backend      仅部署后端 (Django) - 需要中间件已运行"
    echo "  frontend     仅部署前端 (Vue) - 需要中间件已运行"
    echo "  fastapi      仅部署 FastAPI 服务 (含语音 WebSocket) - 需要中间件已运行"
    echo "  nginx        仅部署 Nginx"
    echo "  middleware   仅部署中间件 (MySQL + Redis)"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo "  $0                    # 启动所有服务（含中间件）"
    echo "  $0 middleware         # 仅启动 MySQL + Redis"
    echo "  $0 backend            # 仅重启后端（假设中间件已运行）"
    echo "  $0 -u backend         # 更新代码并部署后端"
    echo "  $0 -r backend         # 重启后端"
    echo "  $0 frontend           # 仅构建并部署前端"
    echo ""
    echo -e "${YELLOW}部署策略:${NC}"
    echo "  - 中间件(middleware): MySQL + Redis，通常不需要频繁重启"
    echo "  - 代码服务: backend, frontend, fastapi，开发时频繁更新"
    echo "  - 建议先启动 middleware，再按需启动代码服务"
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

    # 等待容器启动（web 服务端口不对外映射，检查容器状态）
    wait_for_container "web"

    # 执行数据库迁移（使用 service 名称：web）
    echo -e "${BLUE}执行数据库迁移...${NC}"
    ${DOCKER_COMPOSE} exec -T web python manage.py migrate --noinput

    # 收集静态文件
    echo -e "${BLUE}收集静态文件...${NC}"
    ${DOCKER_COMPOSE} exec -T web python manage.py collectstatic --noinput

    echo -e "${GREEN}后端部署完成！${NC}"
}

# 部署 FastAPI
deploy_kdx_ws() {
    echo -e "${YELLOW}=== 部署 FastAPI 服务 ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps kdx_ws
    # FastAPI 端口不对外映射，检查容器状态
    wait_for_container "kdx-ws-be"
    echo -e "${GREEN}FastAPI 部署完成！${NC}"
}

# 部署 Nginx
deploy_nginx() {
    echo -e "${YELLOW}=== 部署 Nginx ===${NC}"
    
    # 确保前端已构建
    if [ ! -d "${PROJECT_PATH}/kdx-fe/dist" ]; then
        echo -e "${BLUE}前端目录不存在，先构建前端...${NC}"
        build_frontend
    fi
    
    ${DOCKER_COMPOSE} up -d --build --no-deps nginx
    # Nginx有端口映射，检查端口
    wait_for_port "nginx" "80"
    echo -e "${GREEN}Nginx 部署完成！${NC}"
}

# 部署中间件 (MySQL + Redis)
deploy_middleware() {
    echo -e "${YELLOW}=== 部署中间件服务 (MySQL + Redis) ===${NC}"
    
    # 启动 Redis（有端口映射）
    ${DOCKER_COMPOSE} up -d --build --no-deps redis
    wait_for_port "redis" "6379"
    
    # 启动 MySQL（有端口映射）
    ${DOCKER_COMPOSE} up -d --build --no-deps db
    wait_for_port "db" "3306"
    
    echo -e "${GREEN}中间件服务部署完成！${NC}"
}



# 部署所有服务
deploy_all() {
    echo -e "${YELLOW}=== 部署所有服务 ===${NC}"

    # 步骤1: 部署中间件（MySQL + Redis）
    echo -e "\n${BLUE}【步骤1/4】启动中间件${NC}"
    deploy_middleware

    # 步骤2: 部署后端服务
    echo -e "\n${BLUE}【步骤2/4】启动后端服务${NC}"
    deploy_backend

    # 步骤 3: 部署其他代码服务
    echo -e "\n${BLUE}【步骤 3/4】启动 FastAPI 服务${NC}"
    deploy_kdx_ws


    # 步骤4: 构建前端并部署 Nginx
    echo -e "\n${BLUE}【步骤4/4】构建前端并启动 Nginx${NC}"
    deploy_nginx

    echo -e "\n${GREEN}=============================================${NC}"
    echo -e "${GREEN}          所有服务部署完成！                 ${NC}"
    echo -e "${GREEN}=============================================${NC}"
    
    # 显示服务状态
    echo -e "\n${YELLOW}服务状态概览:${NC}"
    ${DOCKER_COMPOSE} ps
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
            all|backend|frontend|fastapi|nginx|middleware)
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
                    deploy_kdx_ws
                    ;;
                nginx)
                    deploy_nginx
                    ;;
                middleware)
                    deploy_middleware
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
                    ${DOCKER_COMPOSE} restart kdx_ws
                    ;;
                nginx)
                    ${DOCKER_COMPOSE} restart nginx
                    ;;
                middleware)
                    ${DOCKER_COMPOSE} restart redis db
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
                    ${DOCKER_COMPOSE} build kdx_ws
                    ;;
                nginx)
                    ${DOCKER_COMPOSE} build nginx
                    ;;
                middleware)
                    ${DOCKER_COMPOSE} build redis db
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
                    deploy_kdx_ws
                    ;;
                nginx)
                    deploy_nginx
                    ;;
                middleware)
                    deploy_middleware
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
                    ${DOCKER_COMPOSE} logs -f kdx_ws
                    ;;
                nginx)
                    ${DOCKER_COMPOSE} logs -f nginx
                    ;;
                middleware)
                    ${DOCKER_COMPOSE} logs -f redis db
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

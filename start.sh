#!/bin/bash

# KDX 项目一键部署脚本
# 本地构建 + 启动，支持按需部署、智能启动顺序、健康检查

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MAX_WAIT=300
CHECK_INTERVAL=2

DOCKER_COMPOSE="docker compose"
if ! docker compose version &> /dev/null; then
    if command -v docker-compose &> /dev/null; then
        DOCKER_COMPOSE="docker-compose"
    else
        echo -e "${RED}Error: docker-compose not found${NC}"
        exit 1
    fi
fi

if [ ! -f "${PROJECT_PATH}/docker-compose.yaml" ]; then
    echo -e "${RED}Error: Please run in project root${NC}"
    exit 1
fi

is_service_running() {
    local service=$1
    ${DOCKER_COMPOSE} ps -q "$service" | grep -q .
}

wait_for_container() {
    local container_name=$1
    local timeout=${2:-$MAX_WAIT}

    echo -e "${BLUE}Waiting for $container_name...${NC}"

    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        local container_id=$(${DOCKER_COMPOSE} ps -q "$container_name" 2>/dev/null)
        if [ -z "$container_id" ]; then
            container_id=$(docker ps -q --filter "name=^/${container_name}$" 2>/dev/null)
        fi

        if [ -n "$container_id" ]; then
            local status=$(docker inspect --format='{{.State.Status}}' "$container_id" 2>/dev/null)
            if [ "$status" = "running" ]; then
                echo -e "${GREEN}$container_name ready${NC}"
                return 0
            fi
        fi
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
        echo -ne "${YELLOW}.${NC}"
    done

    echo -e "\n${RED}Error: $container_name timeout${NC}"
    ${DOCKER_COMPOSE} logs "$container_name" 2>/dev/null | tail -20 || docker logs "$container_name" 2>/dev/null | tail -20
    return 1
}

wait_for_port() {
    local service=$1
    local port=$2
    local host=${3:-localhost}
    local timeout=${4:-$MAX_WAIT}

    echo -e "${BLUE}Waiting for $service on port $port...${NC}"

    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if is_service_running "$service"; then
            if timeout 1 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
                echo -e "${GREEN}$service ready${NC}"
                return 0
            fi
        fi
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
        echo -ne "${YELLOW}.${NC}"
    done

    echo -e "\n${RED}Error: $service timeout${NC}"
    ${DOCKER_COMPOSE} logs "$service" | tail -20
    return 1
}

cleanup_docker() {
    echo -e "${BLUE}Cleaning up dangling images...${NC}"
    docker image prune -f 2>/dev/null || true
    echo -e "${GREEN}Cleanup complete!${NC}"
}

show_help() {
    echo -e "${BLUE}=== KDX Deployment Script ===${NC}"
    echo ""
    echo "Usage: $0 [options] [module]"
    echo ""
    echo "Options:"
    echo "  -h, --help          Show this help"
    echo "  -s, --start         Start services (default)"
    echo "  -d, --down          Stop and remove containers"
    echo "  -r, --restart       Restart services"
    echo "  -b, --build         Build images only"
    echo "  -u, --update        Pull code and deploy"
    echo "  -l, --logs          View logs"
    echo "  -c, --clean         Clean unused resources"
    echo ""
    echo "Modules:"
    echo "  all          Deploy all services"
    echo "  backend      Deploy Django backend"
    echo "  frontend     Deploy Vue frontend"
    echo "  fastapi      Deploy FastAPI service"
    echo "  nginx        Deploy Nginx"
    echo "  middleware   Deploy MySQL + Redis"
    echo ""
    echo "Examples:"
    echo "  $0                    # Start all services"
    echo "  $0 middleware         # Start MySQL + Redis"
    echo "  $0 backend            # Build and start backend"
    echo "  $0 -u backend         # Update code and deploy backend"
    echo "  $0 -r backend         # Restart backend"
}

build_frontend() {
    echo -e "${YELLOW}=== Building frontend ===${NC}"
    cd "${PROJECT_PATH}/kdx-fe"

    if [ ! -d "node_modules" ]; then
        echo -e "${BLUE}Installing dependencies...${NC}"
        if [ -f "package-lock.json" ]; then
            npm ci
        else
            npm install
        fi
    fi

    echo -e "${BLUE}Building...${NC}"
    npm run build:prod

    cd "${PROJECT_PATH}"
}

deploy_backend() {
    echo -e "${YELLOW}=== Deploying backend ===${NC}"

    # 检查并复制 InsightFace 模型文件
    local model_file="buffalo_l.zip"
    local model_src="/tmp/${model_file}"
    local model_dst="${PROJECT_PATH}/kdx-be/${model_file}"

    if [ -f "${model_src}" ] && [ ! -f "${model_dst}" ]; then
        echo -e "${BLUE}复制模型文件: ${model_src} -> ${model_dst}${NC}"
        cp "${model_src}" "${model_dst}"
    elif [ ! -f "${model_src}" ] && [ ! -f "${model_dst}" ]; then
        echo -e "${RED}错误: 未找到模型文件 ${model_file}${NC}"
        echo -e "${YELLOW}请将 ${model_file} 放在 /tmp 或 kdx-be/ 目录下${NC}"
        exit 1
    fi

    ${DOCKER_COMPOSE} up -d --build --no-deps web
    wait_for_container "web"

    echo -e "${BLUE}Running migrations...${NC}"
    ${DOCKER_COMPOSE} exec -T web python manage.py migrate --noinput

    echo -e "${BLUE}Collecting static files...${NC}"
    ${DOCKER_COMPOSE} exec -T web python manage.py collectstatic --noinput

    cleanup_docker

    echo -e "${GREEN}Backend deployed!${NC}"
}

deploy_kdx_ws() {
    echo -e "${YELLOW}=== Deploying FastAPI ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps kdx_ws
    wait_for_container "kdx_ws"

    cleanup_docker

    echo -e "${GREEN}FastAPI deployed!${NC}"
}

deploy_nginx() {
    echo -e "${YELLOW}=== Deploying Nginx ===${NC}"

    if [ ! -d "${PROJECT_PATH}/kdx-fe/dist" ]; then
        echo -e "${RED}Warning: dist not found!${NC}"
        echo -e "${YELLOW}Building frontend...${NC}"
        build_frontend
    fi

    ${DOCKER_COMPOSE} up -d --build --no-deps nginx
    wait_for_port "nginx" "80"

    cleanup_docker

    echo -e "${GREEN}Nginx deployed!${NC}"
}

deploy_middleware() {
    echo -e "${YELLOW}=== Deploying middleware ===${NC}"

    ${DOCKER_COMPOSE} up -d --no-deps redis
    wait_for_port "redis" "6379"

    ${DOCKER_COMPOSE} up -d --no-deps db
    wait_for_port "db" "3306"

    echo -e "${GREEN}Middleware deployed!${NC}"
}

deploy_all() {
    echo -e "${YELLOW}=== Deploying all services ===${NC}"

    echo -e "\n${BLUE}[Step 1/4] Starting middleware${NC}"
    deploy_middleware

    echo -e "\n${BLUE}[Step 2/4] Starting backend${NC}"
    deploy_backend

    echo -e "\n${BLUE}[Step 3/4] Starting FastAPI${NC}"
    deploy_kdx_ws

    echo -e "\n${BLUE}[Step 4/4] Starting Nginx${NC}"
    deploy_nginx

    echo -e "\n${GREEN}=== All services deployed! ===${NC}"

    echo -e "\n${YELLOW}Service status:${NC}"
    ${DOCKER_COMPOSE} ps
}

pull_code() {
    echo -e "${YELLOW}=== Pulling latest code ===${NC}"
    git fetch origin main
    git reset --hard origin/main
    echo -e "${GREEN}Code pulled!${NC}"
}

main() {
    local action="start"
    local modules=("all")

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
                echo -e "${RED}Error: Unknown parameter '$1'${NC}"
                show_help
                exit 1
                ;;
        esac
    done

    cd "${PROJECT_PATH}"

    case "$action" in
        start)
            case "${modules[0]}" in
                all) deploy_all ;;
                backend) deploy_backend ;;
                frontend) build_frontend; deploy_nginx ;;
                fastapi) deploy_kdx_ws ;;
                nginx) deploy_nginx ;;
                middleware) deploy_middleware ;;
            esac
            ;;

        down)
            echo -e "${YELLOW}=== Stopping containers ===${NC}"
            ${DOCKER_COMPOSE} down
            echo -e "${GREEN}Containers stopped!${NC}"
            ;;

        restart)
            echo -e "${YELLOW}=== Restarting services ===${NC}"
            case "${modules[0]}" in
                all) ${DOCKER_COMPOSE} restart ;;
                backend) ${DOCKER_COMPOSE} restart web ;;
                frontend) ${DOCKER_COMPOSE} restart nginx ;;
                fastapi) ${DOCKER_COMPOSE} restart kdx_ws ;;
                nginx) ${DOCKER_COMPOSE} restart nginx ;;
                middleware) ${DOCKER_COMPOSE} restart redis db ;;
            esac
            echo -e "${GREEN}Services restarted!${NC}"
            ;;

        build)
            echo -e "${YELLOW}=== Building images ===${NC}"
            case "${modules[0]}" in
                all) ${DOCKER_COMPOSE} build ;;
                backend) ${DOCKER_COMPOSE} build web ;;
                frontend) build_frontend; ${DOCKER_COMPOSE} build nginx ;;
                fastapi) ${DOCKER_COMPOSE} build kdx_ws ;;
                nginx) ${DOCKER_COMPOSE} build nginx ;;
                middleware) ${DOCKER_COMPOSE} build redis db ;;
            esac
            cleanup_docker
            echo -e "${GREEN}Images built!${NC}"
            ;;

        update)
            pull_code
            case "${modules[0]}" in
                all) deploy_all ;;
                backend) deploy_backend ;;
                frontend) build_frontend; deploy_nginx ;;
                fastapi) deploy_kdx_ws ;;
                nginx) deploy_nginx ;;
                middleware) deploy_middleware ;;
            esac
            ;;

        logs)
            echo -e "${YELLOW}=== Viewing logs ===${NC}"
            case "${modules[0]}" in
                all) ${DOCKER_COMPOSE} logs -f ;;
                backend) ${DOCKER_COMPOSE} logs -f web ;;
                frontend) ${DOCKER_COMPOSE} logs -f nginx ;;
                fastapi) ${DOCKER_COMPOSE} logs -f kdx_ws ;;
                nginx) ${DOCKER_COMPOSE} logs -f nginx ;;
                middleware) ${DOCKER_COMPOSE} logs -f redis db ;;
            esac
            ;;

        clean)
            echo -e "${YELLOW}=== Cleaning resources ===${NC}"
            docker stop $(docker ps -aq) 2>/dev/null || true
            docker rm $(docker ps -aq) 2>/dev/null || true
            docker image prune -af
            docker volume prune -f
            docker network prune -f
            echo -e "${GREEN}Cleanup complete!${NC}"
            ;;
    esac
}

main "$@"
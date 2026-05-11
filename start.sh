#!/bin/bash

# ==============================================================================
# KDX 椤圭洰涓€閿儴缃茶剼鏈?# 鏀寔鎸夐渶閮ㄧ讲鍚庣銆佸墠绔€丗astAPI銆丯ginx绛夋ā鍧?# ==============================================================================

set -e

# 棰滆壊瀹氫箟
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 椤圭洰璺緞
PROJECT_PATH=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DOCKER_COMPOSE="docker-compose"

# 妫€鏌?docker-compose 鍛戒护
if ! command -v docker-compose &> /dev/null; then
    if command -v docker &> /dev/null && docker compose version &> /dev/null; then
        DOCKER_COMPOSE="docker compose"
    else
        echo -e "${RED}閿欒: 鏈壘鍒?docker-compose 鎴?docker compose${NC}"
        exit 1
    fi
fi

# 妫€鏌ユ槸鍚﹀湪椤圭洰鏍圭洰褰?if [ ! -f "${PROJECT_PATH}/docker-compose.yaml" ]; then
    echo -e "${RED}閿欒: 璇峰湪椤圭洰鏍圭洰褰曡繍琛屾鑴氭湰${NC}"
    exit 1
fi

# 鏄剧ず甯姪淇℃伅
show_help() {
    echo -e "${BLUE}=============================================${NC}"
    echo -e "${BLUE}          KDX 椤圭洰涓€閿儴缃茶剼鏈?               ${NC}"
    echo -e "${BLUE}=============================================${NC}"
    echo ""
    echo -e "${YELLOW}浣跨敤鏂规硶:${NC}"
    echo "  $0 [閫夐」] [妯″潡...]"
    echo ""
    echo -e "${YELLOW}閫夐」:${NC}"
    echo "  -h, --help          鏄剧ず甯姪淇℃伅"
    echo "  -s, --start         鍚姩鏈嶅姟锛堥粯璁わ級"
    echo "  -d, --down          鍋滄骞剁Щ闄ゅ鍣?
    echo "  -r, --restart       閲嶅惎鏈嶅姟"
    echo "  -b, --build         鏋勫缓闀滃儚锛堜笉鍚姩锛?
    echo "  -u, --update        鎷夊彇鏈€鏂颁唬鐮佸苟閮ㄧ讲"
    echo "  -l, --logs          鏌ョ湅鏃ュ織"
    echo "  -c, --clean         娓呯悊鍋滄鐨勫鍣ㄥ拰鏃犵敤闀滃儚"
    echo ""
    echo -e "${YELLOW}妯″潡锛堝彲閫夛紝涓嶆寚瀹氬垯閮ㄧ讲鍏ㄩ儴锛?${NC}"
    echo "  all          閮ㄧ讲鎵€鏈夋湇鍔★紙榛樿锛?
    echo "  backend      浠呴儴缃插悗绔?(Django)"
    echo "  frontend     浠呴儴缃插墠绔?(Vue)"
    echo "  fastapi      浠呴儴缃?FastAPI 鏈嶅姟"
    echo "  nginx        浠呴儴缃?Nginx"
    echo "  db           浠呴儴缃叉暟鎹簱 (MySQL + Redis)"
    echo "  voice_ws     浠呴儴缃茶闊?WebSocket 鏈嶅姟"
    echo ""
    echo -e "${YELLOW}绀轰緥:${NC}"
    echo "  $0                    # 鍚姩鎵€鏈夋湇鍔?
    echo "  $0 -b                 # 鏋勫缓鎵€鏈夐暅鍍?
    echo "  $0 backend frontend   # 浠呭惎鍔ㄥ悗绔拰鍓嶇"
    echo "  $0 -u backend         # 鏇存柊浠ｇ爜骞堕儴缃插悗绔?
    echo "  $0 -r nginx           # 閲嶅惎 Nginx"
    echo "  $0 -l web             # 鏌ョ湅 web 瀹瑰櫒鏃ュ織"
    echo ""
}

# 鏋勫缓鍓嶇
build_frontend() {
    echo -e "${YELLOW}=== 鏋勫缓鍓嶇椤圭洰 ===${NC}"
    cd "${PROJECT_PATH}/kdx-fe"
    
    if [ ! -d "node_modules" ]; then
        echo -e "${BLUE}瀹夎渚濊禆...${NC}"
        npm ci --only=production
    fi
    
    echo -e "${BLUE}鎵ц鏋勫缓...${NC}"
    npm run build
    
    cd "${PROJECT_PATH}"
}

# 閮ㄧ讲鍚庣
deploy_backend() {
    echo -e "${YELLOW}=== 閮ㄧ讲鍚庣鏈嶅姟 ===${NC}"
    
    # 鏋勫缓骞跺惎鍔ㄥ悗绔鍣?    ${DOCKER_COMPOSE} up -d --build --no-deps web
    
    # 绛夊緟瀹瑰櫒鍚姩
    sleep 5
    
    # 鎵ц鏁版嵁搴撹縼绉?    echo -e "${BLUE}鎵ц鏁版嵁搴撹縼绉?..${NC}"
    ${DOCKER_COMPOSE} exec -T kdx-be python manage.py migrate --noinput
    
    # 鏀堕泦闈欐€佹枃浠?    echo -e "${BLUE}鏀堕泦闈欐€佹枃浠?..${NC}"
    ${DOCKER_COMPOSE} exec -T kdx-be python manage.py collectstatic --noinput
    
    echo -e "${GREEN}鍚庣閮ㄧ讲瀹屾垚锛?{NC}"
}

# 閮ㄧ讲 FastAPI
deploy_fastapi() {
    echo -e "${YELLOW}=== 閮ㄧ讲 FastAPI 鏈嶅姟 ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps fastapi
    echo -e "${GREEN}FastAPI 閮ㄧ讲瀹屾垚锛?{NC}"
}

# 閮ㄧ讲 Nginx
deploy_nginx() {
    echo -e "${YELLOW}=== 閮ㄧ讲 Nginx ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps nginx
    echo -e "${GREEN}Nginx 閮ㄧ讲瀹屾垚锛?{NC}"
}

# 閮ㄧ讲鏁版嵁搴?deploy_db() {
    echo -e "${YELLOW}=== 閮ㄧ讲鏁版嵁搴撴湇鍔?===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps redis db
    echo -e "${GREEN}鏁版嵁搴撴湇鍔￠儴缃插畬鎴愶紒${NC}"
}

# 閮ㄧ讲璇煶 WebSocket
deploy_voice_ws() {
    echo -e "${YELLOW}=== 閮ㄧ讲璇煶 WebSocket 鏈嶅姟 ===${NC}"
    ${DOCKER_COMPOSE} up -d --build --no-deps voice_ws
    echo -e "${GREEN}璇煶 WebSocket 閮ㄧ讲瀹屾垚锛?{NC}"
}

# 閮ㄧ讲鎵€鏈夋湇鍔?deploy_all() {
    echo -e "${YELLOW}=== 閮ㄧ讲鎵€鏈夋湇鍔?===${NC}"
    
    # 鍏堥儴缃叉暟鎹簱
    deploy_db
    
    # 閮ㄧ讲鍚庣
    deploy_backend
    
    # 閮ㄧ讲璇煶 WebSocket
    deploy_voice_ws
    
    # 閮ㄧ讲 FastAPI
    deploy_fastapi
    
    # 鏋勫缓鍓嶇
    build_frontend
    
    # 閮ㄧ讲 Nginx
    deploy_nginx
    
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}          鎵€鏈夋湇鍔￠儴缃插畬鎴愶紒                  ${NC}"
    echo -e "${GREEN}=============================================${NC}"
}

# 鎷夊彇鏈€鏂颁唬鐮?pull_code() {
    echo -e "${YELLOW}=== 鎷夊彇鏈€鏂颁唬鐮?===${NC}"
    git pull origin main
    echo -e "${GREEN}浠ｇ爜鎷夊彇瀹屾垚锛?{NC}"
}

# 涓诲嚱鏁?main() {
    local action="start"
    local modules=("all")
    
    # 瑙ｆ瀽鍙傛暟
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
                echo -e "${RED}閿欒: 鏈煡鍙傛暟 '$1'${NC}"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 鍒囨崲鍒伴」鐩洰褰?    cd "${PROJECT_PATH}"
    
    # 鎵ц鎿嶄綔
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
            echo -e "${YELLOW}=== 鍋滄骞剁Щ闄ゅ鍣?===${NC}"
            ${DOCKER_COMPOSE} down
            echo -e "${GREEN}瀹瑰櫒宸插仠姝㈠苟绉婚櫎锛?{NC}"
            ;;
            
        restart)
            echo -e "${YELLOW}=== 閲嶅惎鏈嶅姟 ===${NC}"
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
            echo -e "${GREEN}鏈嶅姟宸查噸鍚紒${NC}"
            ;;
            
        build)
            echo -e "${YELLOW}=== 鏋勫缓闀滃儚 ===${NC}"
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
            echo -e "${GREEN}闀滃儚鏋勫缓瀹屾垚锛?{NC}"
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
            echo -e "${YELLOW}=== 鏌ョ湅鏃ュ織 ===${NC}"
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
            echo -e "${YELLOW}=== 娓呯悊鏃犵敤璧勬簮 ===${NC}"
            echo -e "${BLUE}鍋滄鎵€鏈夊鍣?..${NC}"
            docker stop $(docker ps -aq) 2>/dev/null || true
            
            echo -e "${BLUE}鍒犻櫎鍋滄鐨勫鍣?..${NC}"
            docker rm $(docker ps -aq) 2>/dev/null || true
            
            echo -e "${BLUE}鍒犻櫎鏃犵敤闀滃儚...${NC}"
            docker image prune -f
            
            echo -e "${BLUE}鍒犻櫎鏃犵敤缃戠粶...${NC}"
            docker network prune -f
            
            echo -e "${GREEN}娓呯悊瀹屾垚锛?{NC}"
            ;;
    esac
}

# 鎵ц涓诲嚱鏁?main "$@"


# nginx 镜像 (compose/nginx/Dockerfile)
# 固定版本: 1.27 是当前稳定线, 避免 latest 在服务器升级时意外变更
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:1.27

# 注: 生产环境 compose 会用 ./compose/nginx/default.conf 卷挂载覆盖此文件,
#     镜像内置配置仅作独立运行/兜底用。用 COPY 而非 ADD(语义更明确, 无自动解压副作用)。
COPY default.conf /etc/nginx/conf.d/

# 关闭守护模式, 前台运行
CMD ["nginx", "-g", "daemon off;"]

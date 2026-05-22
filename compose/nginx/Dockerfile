# nginx镜像compose/nginx/Dockerfile
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/nginx:latest

# 删除原有配置文件，创建静态资源文件夹和ssl证书保存文件夹
#RUN rm /etc/nginx/conf.d/default.conf \

# 添加配置文件
ADD default.conf /etc/nginx/conf.d/

# 关闭守护模式
CMD ["nginx", "-g", "daemon off;"]

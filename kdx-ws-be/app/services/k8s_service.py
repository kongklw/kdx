"""K8s pods 查询服务 (迁移自 kdx-be/k8s/views.py)。

说明: 源 Django 视图 Pos 中 self.v1 从未初始化 (加载 kube config 的代码被注释),
该端点在线上始终返回 {"code": 205, "data": None, "msg": "'Pos' object has no attribute 'v1'"}。
此处按其意图实现可用的 list_pod_for_all_namespaces: 优先本地 kubeconfig, 其次
in-cluster 配置; 均不可用时抛出异常, 由 api 层降级为与 Django 相同的 205 响应结构。
"""
from typing import List


class K8sUnavailableError(Exception):
    """kube 配置不可用或集群访问失败"""


def list_all_pods() -> List[str]:
    """列出所有命名空间的 pod, 返回 "pod_ip namespace pod_name" 行列表"""
    from kubernetes import client, config

    v1 = None
    try:
        # 1. 本地 kubeconfig (~/.kube/config)
        config.load_kube_config()
        v1 = client.CoreV1Api()
    except Exception:
        try:
            # 2. Pod 内 in-cluster ServiceAccount 配置
            config.load_incluster_config()
            v1 = client.CoreV1Api()
        except Exception as exc:
            raise K8sUnavailableError(f"kube config 不可用: {exc}")

    ret = v1.list_pod_for_all_namespaces(watch=False)
    return [f"{i.status.pod_ip}\t{i.metadata.namespace}\t{i.metadata.name}" for i in ret.items]

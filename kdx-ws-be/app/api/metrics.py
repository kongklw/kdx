"""
Prometheus 指标暴露端点 (生产可观测性)
GET /metrics → 文本格式, 供 Prometheus 抓取
"""

from fastapi import APIRouter, Response

from ..core.metrics import get_metrics

router = APIRouter()


def _refresh_breaker_gauges() -> None:
    """每次抓取前把熔断器状态刷成 gauge (懒刷新, 不引入定时任务)"""
    m = get_metrics()
    try:
        from ..assistant.llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        for name, snap in gw.breaker_snapshots().items():
            labels = {"breaker": name}
            m.set("llm_breaker_state", 1.0, {**labels, "state": snap["state"]})
            m.set("llm_breaker_total", snap["total"], labels)
            m.set("llm_breaker_failures", snap["failures"], labels)
    except Exception:
        pass


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    _refresh_breaker_gauges()
    return Response(
        content=get_metrics().render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

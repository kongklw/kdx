"""RAG HTTP 兼容桥接 (老 Django /rag/ 端点, 不迁移老检索实现)

老实现: chroma 向量检索 top3 → 拼接 prompt → qwen 生成 (langgraph)
桥接实现: RetrievalService (BM25+向量混合检索+精排, app/rag/service.py)
          → llm_gateway 生成 (与 /ws/rag_query 同链路)

响应形状与老端点完全一致 (DRF 风格, HTTP 200, 业务码在 body.code):
  成功: {"code": 200, "msg": "ok", "data": {"answer", "sources", "query"}}
  空查询: {"code": 400, "msg": "查询内容不能为空", "data": null}
  异常: {"code": 500, "msg": str(e), "data": null}

source 字段映射 (老形状 ← RetrievalService):
  title      ← Source.title
  filename   ← Source.filename
  category   ← Source.category
  topics     ← hits[i].meta['topics']      (老 chroma metadata 字段, 缺省 [])
  age_ranges ← hits[i].meta['age_ranges']  (老 chroma metadata 字段, 缺省 [])
  (新链路的 index/section 字段不输出, 保持老形状不变)
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.database import get_db
from ..schemas.rag import RagQueryRequest
from .deps import require_user_id

MAX_QUERY_LEN = 500  # 输入限长 (防 prompt 注入), 与 /ws/rag_query 一致

# 老端点 build_prompt 中的 system prompt 原文
_SYSTEM_PROMPT = """你是一位专业的育儿知识助手。请根据提供的知识库内容，回答用户的问题。

规则：
1. 优先使用知识库中的信息进行回答
2. 如果知识库中没有相关信息，请明确说明"知识库中未找到相关信息"
3. 回答要简洁、准确，避免冗长
4. 可以引用知识库中的来源信息
"""


def create_rag_http_router(settings: Settings):
    router = APIRouter(prefix="/rag", tags=["rag"])

    @router.post("/query/")
    async def rag_query(request: Request, body: RagQueryRequest, db: Session = Depends(get_db)):
        """知识问答 (对应老 Django RAGQueryView)"""
        require_user_id(request, settings)  # IsAuthenticated

        query = (body.query or '').strip()
        if not query:
            return JSONResponse({"code": 400, "msg": "查询内容不能为空", "data": None})

        try:
            # ① 统一检索 (混合检索 + 精排 + 父章节扩展 + 预算裁剪)
            #    知识库为空/不可用时降级为空结果 (兼容要求: 不得 500)
            from ..rag.service import RetrievalRequest, get_retrieval_service

            sources = []
            context = "(知识库未返回内容)"
            try:
                svc = get_retrieval_service()
                result = await svc.search(
                    RetrievalRequest(query=query, top_k=3, fetch=20, enable_rerank=True)
                )
                # source 字段映射: 保持老响应形状 (topics/age_ranges 从 hit.meta 补齐)
                for i, s in enumerate(result.sources):
                    meta = result.hits[i].meta if i < len(result.hits) else {}
                    sources.append({
                        'title': s.title,
                        'filename': s.filename,
                        'category': s.category,
                        'topics': meta.get('topics') or [],
                        'age_ranges': meta.get('age_ranges') or [],
                    })
                context = result.context or context
            except Exception as retrieval_err:
                logger.warning(f"retrieval unavailable, fallback to empty sources: {retrieval_err}")

            # ② LLM 生成 (走 llm_gateway: 熔断/降级, 与 /ws/rag_query 同一出口)
            answer = await _generate(query, context)

            return JSONResponse({
                "code": 200,
                "msg": "ok",
                "data": {"answer": answer, "sources": sources, "query": query},
            })
        except Exception as e:
            logger.exception(e)
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @router.get("/common/")
    async def rag_common(request: Request, db: Session = Depends(get_db)):
        """LLM 探活 (对应老 Django CommonView: 固定问'你是谁')"""
        require_user_id(request, settings)  # IsAuthenticated

        try:
            from langchain_core.messages import HumanMessage

            gw = _get_gateway()
            ans = await gw.ainvoke('chitchat', [HumanMessage(content="你是谁")])
            answer = ans.content if hasattr(ans, 'content') else str(ans)
            return JSONResponse({"code": 200, "msg": "ok", "data": {"answer": answer}})
        except Exception as e:
            logger.exception(e)
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    async def _generate(query: str, context: str) -> str:
        """检索上下文 + 用户问题 → 生成答案 (熔断打开时返回降级文案, 与 WS 行为一致)"""
        from langchain_core.messages import HumanMessage, SystemMessage

        system = SystemMessage(content=(
            f"{_SYSTEM_PROMPT}\n\n知识库内容:\n{context}"
        ))
        gw = _get_gateway()
        try:
            ans = await gw.ainvoke('rag', [system, HumanMessage(content=query)])
            return ans.content if hasattr(ans, 'content') else str(ans)
        except CircuitOpenError:
            return "【系统降级】AI 服务暂时不可用，请稍后重试。"

    def _get_gateway():
        from ..assistant.llm_gateway import get_llm_gateway
        return get_llm_gateway()

    # CircuitOpenError 延迟导入放模块底部, 避免 assistant 包依赖顺序问题
    from ..assistant.resilience import CircuitOpenError  # noqa: E402

    return router

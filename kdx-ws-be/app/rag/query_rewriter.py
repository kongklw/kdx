"""
多轮查询改写 (Query Condense)
==============================

处理多轮对话中的指代/省略, 把 "那辅食呢?" 改写为独立完整的检索 query。

策略: 规则短路优先 (零成本), 规则命中才调 LLM (廉价小模型)。
"""

import re
from typing import List, Optional

from loguru import logger

# 指代/省略触发词: query 含这些词时才需要改写
_REWRITE_TRIGGERS = re.compile(
    r'(那|它|他|她|呢|还要|然后呢|另外|这个|那个|上面说的|刚才|继续|也是|'
    r'能不能|可以吗|呢\?|呢？|怎么办|为什么)',
    re.IGNORECASE,
)


class QueryRewriter:
    """多轮 query condense: 规则短路 → LLM 改写"""

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from ..assistant.llm_gateway import get_llm_gateway
        gw = get_llm_gateway()
        self._llm = gw.get("condense")
        return self._llm

    def condense(self, history: List[str], query: str) -> str:
        """
        把最近 2~3 轮对话 + 当前问题改写为独立完整的检索 query。

        Args:
            history: 最近几轮的 (人类) 消息文本列表, 按时间顺序
            query: 当前问题
        Returns:
            改写后的 query; 无需改写时原样返回
        """
        # 规则短路: query 无指代/省略特征 → 原样返回, 零成本
        if not _REWRITE_TRIGGERS.search(query):
            return query

        # 只取最近 2 轮上下文
        recent = history[-4:] if len(history) > 4 else history
        if not recent:
            return query

        try:
            return self._llm_condense(recent, query)
        except Exception as e:
            logger.warning(f"query condense failed, using original: {e}")
            return query

    def _llm_condense(self, recent: List[str], query: str) -> str:
        from langchain_core.messages import HumanMessage

        dialog = "\n".join(f"用户: {msg}" for msg in recent)
        prompt = (
            "你是一个查询改写器。根据对话历史, 把用户的当前问题改写为一个独立完整、"
            "可以直接用于知识库检索的查询语句。\n"
            "规则:\n"
            "1. 只输出改写后的查询, 不要任何解释\n"
            "2. 保持中文, 简洁完整\n"
            "3. 如果当前问题已经完整, 原样输出\n\n"
            f"对话历史:\n{dialog}\n\n"
            f"当前问题: {query}\n"
            "改写后的查询:"
        )
        llm = self._get_llm()
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = (resp.content or "").strip()
        # 取第一行, 去掉可能的引号
        text = text.split('\n')[0].strip().strip('"\'')
        return text if text else query

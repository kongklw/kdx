"""
人工介入机制 HITL (Human-in-the-Loop)
========================================

核心概念：
  Agent 自动化流程中，某些关键节点需要人工审核、确认或修正后才能继续。
  HITL 是"人在回路"的核心设计，确保 AI 不会在关键决策上失控。

应用场景：
  - 医疗诊断建议需医生确认后才能发给患者
  - 高金额退款需人工审批
  - 内容生成需审核后才能发布
  - Agent 自主决策不确定时暂停等人工指令

在 LangGraph 中的实现：
  - 使用 interrupt() 暂停图执行
  - 状态持久化到 checkpoint
  - 人工处理后用 Command(resume=...) 恢复执行

面试话术：
  "我们的 HITL 基于 LangGraph 的 interrupt + checkpoint 机制。
   Agent 执行到审核节点时调用 interrupt 暂停，当前状态持久化到 checkpoint。
   前端收到 pending 事件后展示给审核人员。审核结果通过 Command(resume=...)
   恢复执行。设计上分了三种审核结果：approve（通过）、reject（驳回重做）、
   edit（人工修正后继续）。超时未审核的会自动告警，不会无限等待。"
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Literal, List
from enum import Enum


# ──────────────────────────────────────────────
# 审核状态
# ──────────────────────────────────────────────

class ReviewStatus(Enum):
    PENDING = "pending"      # 等待人工审核
    APPROVED = "approved"     # 审核通过
    REJECTED = "rejected"     # 审核驳回
    EDITED = "edited"         # 人工修正后通过


@dataclass
class ReviewRequest:
    """人工审核请求"""
    request_id: str
    content: str                             # 待审核内容
    reviewer_id: Optional[str] = None        # 审核人
    status: ReviewStatus = ReviewStatus.PENDING
    comment: str = ""                        # 审核意见
    edited_content: Optional[str] = None     # 修正后的内容
    created_at: float = 0.0
    reviewed_at: Optional[float] = None


# ──────────────────────────────────────────────
# HITL 管理器
# ──────────────────────────────────────────────

class HITLManager:
    """
    人工介入管理器

    职责：
    1. 创建审核请求并暂停执行
    2. 等待人工审核结果
    3. 支持超时自动处理
    4. 记录审核轨迹
    """

    def __init__(self, timeout_seconds: int = 300):
        self._pending: Dict[str, ReviewRequest] = {}
        self._completed: Dict[str, ReviewRequest] = {}
        self._timeout = timeout_seconds
        self._trace: List[Dict] = []

    async def request_review(
        self,
        content: str,
        reviewer_id: Optional[str] = None,
    ) -> ReviewRequest:
        """
        发起审核请求，暂停执行等待人工处理

        对应 LangGraph 的 interrupt()：
          - 当前状态持久化
          - 阻塞等待人工结果
        """
        import time
        request = ReviewRequest(
            request_id=f"REV-{int(time.time() * 1000)}",
            content=content,
            reviewer_id=reviewer_id,
            created_at=time.time(),
        )
        self._pending[request.request_id] = request

        self._trace.append({
            "request_id": request.request_id,
            "action": "review_requested",
            "content_preview": content[:50],
        })

        print(f"  [HITL] 审核请求已创建: {request.request_id}")
        print(f"  [HITL] 待审核内容: {content[:80]}...")
        print(f"  [HITL] 等待人工审核...")

        # 模拟等待人工审核（实际场景中这里会阻塞或 yield）
        await asyncio.sleep(0.5)

        # 模拟审核结果
        await self._simulate_human_review(request.request_id)

        return self._completed.get(request.request_id, request)

    async def _simulate_human_review(self, request_id: str):
        """模拟人工审核过程"""
        request = self._pending.pop(request_id, None)
        if request is None:
            return

        import time
        # 模拟审核结果：通过
        request.status = ReviewStatus.APPROVED
        request.reviewed_at = time.time()
        request.comment = "内容准确，审核通过"
        self._completed[request_id] = request

        self._trace.append({
            "request_id": request_id,
            "action": "review_completed",
            "status": request.status.value,
        })

    async def submit_review(
        self,
        request_id: str,
        status: ReviewStatus,
        comment: str = "",
        edited_content: Optional[str] = None,
    ):
        """人工提交审核结果（实际由前端调接口）"""
        request = self._pending.pop(request_id, None)
        if request is None:
            raise ValueError(f"审核请求不存在或已处理: {request_id}")

        import time
        request.status = status
        request.comment = comment
        request.edited_content = edited_content
        request.reviewed_at = time.time()
        self._completed[request_id] = request

    def get_pending_reviews(self) -> List[ReviewRequest]:
        """获取所有待审核请求"""
        return list(self._pending.values())

    def get_trace(self) -> List[Dict]:
        return self._trace


# ──────────────────────────────────────────────
# Agent 工作流（含 HITL 节点）
# ──────────────────────────────────────────────

async def generate_content_agent(task: str) -> str:
    """生成内容 Agent"""
    print("  [Agent] 生成内容中...")
    return f"【科普文章】{task}：乙肝疫苗需在出生时、1月龄、6月龄各接种一剂。"


async def hitl_review_node(
    content: str,
    hitl: HITLManager,
) -> tuple[str, ReviewStatus]:
    """
    HITL 审核节点

    返回 (处理后的内容, 审核状态)
    - APPROVED: 直接使用原内容
    - EDITED: 使用人工修正后的内容
    - REJECTED: 返回空，触发重做
    """
    review = await hitl.request_review(content, reviewer_id="reviewer_001")

    if review.status == ReviewStatus.APPROVED:
        print(f"  [HITL] 审核通过 ✅")
        return content, ReviewStatus.APPROVED
    elif review.status == ReviewStatus.EDITED and review.edited_content:
        print(f"  [HITL] 人工修正后通过 ✏️")
        return review.edited_content, ReviewStatus.EDITED
    elif review.status == ReviewStatus.REJECTED:
        print(f"  [HITL] 审核驳回 ❌ 需重做")
        return "", ReviewStatus.REJECTED
    else:
        print(f"  [HITL] 超时未审核，走兜底")
        return content, ReviewStatus.PENDING


async def publish_agent(content: str) -> str:
    """发布 Agent"""
    print("  [Agent] 发布内容中...")
    return f"已发布: {content}"


# ──────────────────────────────────────────────
# LangGraph HITL 伪代码
# ──────────────────────────────────────────────

LANGGRAPH_HITL_EXAMPLE = """
# === LangGraph 中的 HITL 实现 ===

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command

class WorkflowState(TypedDict):
    task: str
    draft: str
    final: str
    review_status: str

def generate_node(state):
    # LLM 生成内容
    state["draft"] = llm.generate(state["task"])
    return state

def review_node(state):
    # interrupt 暂停执行，等待人工输入
    review_result = interrupt(
        {
            "content": state["draft"],
            "prompt": "请审核以下内容：",
        }
    )
    # review_result 来自人工通过 Command(resume={"action": "approve"}) 恢复
    if review_result["action"] == "approve":
        state["final"] = state["draft"]
        state["review_status"] = "approved"
    elif review_result["action"] == "edit":
        state["final"] = review_result["edited_content"]
        state["review_status"] = "edited"
    else:
        state["final"] = ""
        state["review_status"] = "rejected"
    return state

def route_after_review(state):
    if state["review_status"] == "rejected":
        return "generate"    # 回退重新生成
    return "publish"         # 发布

def publish_node(state):
    publish(state["final"])
    return state

workflow = StateGraph(WorkflowState)
workflow.add_node("generate", generate_node)
workflow.add_node("review", review_node)
workflow.add_node("publish", publish_node)
workflow.set_entry_point("generate")
workflow.add_edge("generate", "review")
workflow.add_conditional_edges("review", route_after_review)
workflow.add_edge("publish", END)

# 使用 checkpoint 持久化，支持 interrupt/resume
from langgraph.checkpoint.memory import MemorySaver
graph = workflow.compile(checkpointer=MemorySaver())

# 第一次执行：到 review 节点会 interrupt
config = {"configurable": {"thread_id": "thread-1"}}
result = graph.invoke({"task": "写科普"}, config)
# → 此时图暂停，状态保存在 checkpoint

# 人工审核后恢复
graph.invoke(
    Command(resume={"action": "approve", "edited_content": None}),
    config,
)
# → 图继续执行到 publish 节点
"""


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("HITL 人工介入 Demo")
    print("=" * 60)

    hitl = HITLManager(timeout_seconds=60)

    # Step 1: Agent 生成内容
    task = "撰写乙肝疫苗接种科普"
    print(f"\n任务: {task}")
    draft = await generate_content_agent(task)
    print(f"  生成草稿: {draft}")

    # Step 2: HITL 审核节点
    final_content, status = await hitl_review_node(draft, hitl)

    # Step 3: 根据审核结果决定后续
    if status == ReviewStatus.REJECTED:
        # 审核驳回 → 回退重新生成
        print("  审核驳回，重新生成...")
        draft = await generate_content_agent(task)
        final_content, status = await hitl_review_node(draft, hitl)

    # Step 4: 发布
    if final_content:
        result = await publish_agent(final_content)
        print(f"\n最终结果: {result}")
    else:
        print("\n内容审核未通过，发布取消")

    # 打印轨迹
    print(f"\n{'─' * 40}")
    print("HITL 轨迹:")
    for entry in hitl.get_trace():
        print(f"  {entry}")


if __name__ == "__main__":
    asyncio.run(main())

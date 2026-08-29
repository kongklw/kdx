"""
多 Agent 协同 (Multi-Agent Collaboration)
==========================================

核心概念：
  复杂任务需要多个专职 Agent 协作完成。每个 Agent 有自己的角色、工具、提示词，
  通过消息传递 / 共享状态 实现协同。

常见协同模式：
  1. 串行流水线：Agent A → Agent B → Agent C（上一环节输出是下一环节输入）
  2. 并行扇出：Agent A 同时调用 B 和 C，汇总结果
  3. Supervisor 模式：一个 Supervisor Agent 负责任务分解和分发
  4. 辩论模式：多个 Agent 给出不同方案，由裁判 Agent 选优

面试话术：
  "我们的多 Agent 协同采用 Supervisor 模式。Supervisor Agent 负责任务分解、
   分发给专职 Agent（研究 Agent、写作 Agent、审核 Agent），并汇总结果。
   Agent 之间通过共享 State 传递中间结果，避免信息丢失。
   关键设计点：每个 Agent 有独立的 system prompt 和工具集，职责单一，
   可独立迭代。Supervisor 做结果聚合和冲突仲裁。"
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


# ──────────────────────────────────────────────
# 共享状态（Agent 间通信的载体）
# ──────────────────────────────────────────────

@dataclass
class SharedState:
    """多 Agent 共享状态，贯穿整个协同流程"""
    task: str                                    # 原始任务
    research_data: Dict[str, Any] = field(default_factory=dict)   # 研究 Agent 产出
    draft: str = ""                              # 写作 Agent 产出
    review: Dict[str, Any] = field(default_factory=dict)          # 审核 Agent 产出
    final_output: str = ""                       # 最终输出
    agent_trace: List[str] = field(default_factory=list)         # 执行轨迹


# ──────────────────────────────────────────────
# 专职 Agent 定义
# ──────────────────────────────────────────────

async def research_agent(state: SharedState) -> SharedState:
    """研究 Agent：负责信息收集和数据整理"""
    print("  [Research Agent] 收集资料中...")

    # Mock：模拟研究 Agent 的产出
    state.research_data = {
        "vaccine_name": "乙肝疫苗",
        "schedule": "出生时、1月龄、6月龄共三剂",
        "side_effects": ["低热", "注射部位红肿"],
        "contraindications": ["严重湿疹", "免疫缺陷"],
    }
    state.agent_trace.append("research_agent: 资料收集完成")

    return state


async def writing_agent(state: SharedState) -> SharedState:
    """写作 Agent：基于研究结果撰写科普文案"""
    print("  [Writing Agent] 撰写文案中...")

    data = state.research_data
    state.draft = f"""
【乙肝疫苗接种指南】
接种时间：{data.get('schedule', '未知')}
常见不良反应：{', '.join(data.get('side_effects', []))}
禁忌情况：{', '.join(data.get('contraindications', []))}
    """.strip()

    state.agent_trace.append("writing_agent: 文案初稿完成")
    return state


async def review_agent(state: SharedState) -> SharedState:
    """审核 Agent：检查文案准确性和合规性"""
    print("  [Review Agent] 审核中...")

    state.review = {
        "passed": True,
        "score": 0.92,
        "issues": [],
        "suggestions": ["建议补充接种后的注意事项"],
    }

    state.agent_trace.append(f"review_agent: 审核通过 (score={state.review['score']})")
    return state


# ──────────────────────────────────────────────
# Supervisor Agent（协同编排核心）
# ──────────────────────────────────────────────

class SupervisorAgent:
    """
    Supervisor Agent：负责多 Agent 协同编排

    职责：
    1. 任务分解：将复杂任务拆成子任务
    2. 任务分发：将子任务分配给专职 Agent
    3. 结果聚合：收集各 Agent 产出
    4. 冲突仲裁：当 Agent 结果冲突时做决策
    5. 质量把关：审核不通过时可回退重做
    """

    def __init__(self):
        self.agents: Dict[str, Any] = {}
        self.max_retries = 2  # 审核不通过时最多重试次数

    def register_agent(self, name: str, agent_func):
        """注册专职 Agent"""
        self.agents[name] = agent_func

    async def execute(self, task: str) -> SharedState:
        """执行编排"""
        state = SharedState(task=task)
        state.agent_trace.append(f"supervisor: 接收任务 → {task}")

        # 串行流水线：研究 → 写作 → 审核
        pipeline = ["research_agent", "writing_agent", "review_agent"]

        for agent_name in pipeline:
            agent_func = self.agents.get(agent_name)
            if agent_func is None:
                raise RuntimeError(f"Agent '{agent_name}' not registered")

            print(f"  [Supervisor] 调度 → {agent_name}")
            state = await agent_func(state)

            # 审核不通过 → 回退到写作 Agent 重做
            if agent_name == "review_agent" and not state.review.get("passed", False):
                retries = 0
                while retries < self.max_retries and not state.review.get("passed"):
                    print(f"  [Supervisor] 审核未通过，回退重做 (retry={retries+1})")
                    state = await self.agents["writing_agent"](state)
                    state = await self.agents["review_agent"](state)
                    retries += 1

        # 最终输出
        state.final_output = state.draft
        state.agent_trace.append("supervisor: 任务完成")

        return state


# ──────────────────────────────────────────────
# 并行扇出示例
# ──────────────────────────────────────────────

async def parallel_research(state: SharedState) -> SharedState:
    """并行扇出：同时调用多个研究 Agent，汇总结果"""
    print("  [Parallel] 并行启动多个研究 Agent...")

    async def research_vaccine():
        await asyncio.sleep(0.01)  # 模拟耗时
        return {"vaccine_info": "乙肝疫苗三剂接种程序"}

    async def research_feeding():
        await asyncio.sleep(0.01)
        return {"feeding_info": "6月龄开始添加辅食"}

    async def research_development():
        await asyncio.sleep(0.01)
        return {"dev_info": "6月龄宝宝可独坐"}

    # 并行执行
    results = await asyncio.gather(
        research_vaccine(),
        research_feeding(),
        research_development(),
    )

    # 聚合结果
    for r in results:
        state.research_data.update(r)

    state.agent_trace.append("parallel_research: 3个Agent并行完成")
    return state


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("多 Agent 协同 Demo（Supervisor 模式）")
    print("=" * 60)

    # 初始化 Supervisor
    supervisor = SupervisorAgent()
    supervisor.register_agent("research_agent", research_agent)
    supervisor.register_agent("writing_agent", writing_agent)
    supervisor.register_agent("review_agent", review_agent)

    # 执行任务
    task = "撰写一篇关于乙肝疫苗接种的科普文章"
    print(f"\n任务: {task}\n")

    state = await supervisor.execute(task)

    print(f"\n{'─' * 40}")
    print("最终输出:")
    print(state.final_output)
    print(f"\n执行轨迹:")
    for trace in state.agent_trace:
        print(f"  {trace}")

    # 并行扇出示例
    print(f"\n{'=' * 60}")
    print("并行扇出 Demo")
    print("=" * 60)
    print()
    state2 = SharedState(task="并行研究")
    state2 = await parallel_research(state2)
    print(f"  聚合结果: {state2.research_data}")


if __name__ == "__main__":
    asyncio.run(main())

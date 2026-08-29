"""
Tool / Function Calling
=========================

核心概念：
  LLM 通过 Function Calling 机制调用外部工具，实现"感知-决策-执行"闭环。
  LLM 负责"决策"（决定调用哪个工具、传什么参数），工具负责"执行"。

工作流程：
  1. 将工具定义（名字、描述、参数 schema）传给 LLM
  2. LLM 分析用户意图，决定是否调用工具
  3. LLM 返回 tool_calls（工具名 + 参数 JSON）
  4. Agent 执行工具，拿到结果
  5. 将工具结果作为 ToolMessage 反馈给 LLM
  6. LLM 基于结果生成最终回复

在 LangChain 中的实现：
  - @tool 装饰器自动生成工具 schema
  - create_react_agent / create_agent 自动编排 tool calling 循环

面试话术：
  "我们的 Function Calling 用 LangChain 的 @tool 装饰器定义工具。
   每个工具有 name、description、args_schema，LLM 通过这些信息做决策。
   Agent 框架自动编排调用循环：LLM 输出 tool_calls → 执行工具 →
   ToolMessage 反馈 → LLM 继续推理。
   我在语音 Agent 项目中定义了 add_to_order、confirm_order 等工具，
   通过 ToolCallEvent 和 ToolResultEvent 做流式事件上报，
   前端实时看到工具调用过程。"
"""

import json
import asyncio
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable


# ──────────────────────────────────────────────
# 工具定义（模拟 LangChain @tool 装饰器）
# ──────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """工具定义：名称、描述、参数 schema、执行函数"""
    name: str
    description: str
    parameters: Dict[str, Any]          # JSON Schema
    handler: Callable                   # 实际执行函数


# 工具 1：查询疫苗信息
def query_vaccine(vaccine_name: str, age_months: int = 0) -> str:
    """查询疫苗接种信息"""
    vaccine_db = {
        "乙肝": {"schedule": "出生时、1月龄、6月龄", "doses": 3},
        "卡介苗": {"schedule": "出生时", "doses": 1},
        "脊灰": {"schedule": "2月龄、3月龄、4月龄", "doses": 4},
    }
    info = vaccine_db.get(vaccine_name)
    if info:
        return json.dumps({"vaccine": vaccine_name, **info, "age": age_months}, ensure_ascii=False)
    return json.dumps({"error": f"未找到疫苗: {vaccine_name}"}, ensure_ascii=False)


# 工具 2：预约门诊
def book_appointment(hospital: str, date: str, department: str = "儿科") -> str:
    """预约门诊挂号"""
    return json.dumps({
        "success": True,
        "hospital": hospital,
        "department": department,
        "date": date,
        "appointment_id": f"APT-{hash(hospital + date) % 10000}",
    }, ensure_ascii=False)


# 工具 3：计算 BMI
def calculate_bmi(weight_kg: float, height_m: float) -> str:
    """计算身体质量指数"""
    if height_m <= 0:
        return json.dumps({"error": "身高必须大于0"})
    bmi = weight_kg / (height_m ** 2)
    if bmi < 18.5:
        category = "偏瘦"
    elif bmi < 24:
        category = "正常"
    elif bmi < 28:
        category = "超重"
    else:
        category = "肥胖"
    return json.dumps({"bmi": round(bmi, 1), "category": category}, ensure_ascii=False)


# 注册工具
TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="query_vaccine",
        description="查询疫苗接种信息，包括接种时间和剂次",
        parameters={
            "type": "object",
            "properties": {
                "vaccine_name": {"type": "string", "description": "疫苗名称，如'乙肝'、'卡介苗'"},
                "age_months": {"type": "integer", "description": "宝宝月龄", "default": 0},
            },
            "required": ["vaccine_name"],
        },
        handler=query_vaccine,
    ),
    ToolDefinition(
        name="book_appointment",
        description="预约门诊挂号",
        parameters={
            "type": "object",
            "properties": {
                "hospital": {"type": "string", "description": "医院名称"},
                "date": {"type": "string", "description": "预约日期 YYYY-MM-DD"},
                "department": {"type": "string", "description": "科室", "default": "儿科"},
            },
            "required": ["hospital", "date"],
        },
        handler=book_appointment,
    ),
    ToolDefinition(
        name="calculate_bmi",
        description="计算身体质量指数(BMI)",
        parameters={
            "type": "object",
            "properties": {
                "weight_kg": {"type": "number", "description": "体重(公斤)"},
                "height_m": {"type": "number", "description": "身高(米)"},
            },
            "required": ["weight_kg", "height_m"],
        },
        handler=calculate_bmi,
    ),
]


# ──────────────────────────────────────────────
# LLM Mock（模拟 LLM 输出 tool_calls）
# ──────────────────────────────────────────────

def mock_llm_tool_calls(user_input: str) -> List[Dict[str, Any]]:
    """
    模拟 LLM 决策：分析用户意图，返回 tool_calls

    真实场景中，这是 LLM 的输出：
      response = client.chat.completions.create(
          model="qwen-plus",
          messages=[...],
          tools=tool_schemas,
      )
      return response.choices[0].message.tool_calls
    """
    # 模拟 LLM 的意图理解和工具选择
    if "疫苗" in user_input or "接种" in user_input:
        return [{
            "id": "call_001",
            "name": "query_vaccine",
            "args": {"vaccine_name": "乙肝", "age_months": 6},
        }]
    elif "预约" in user_input or "挂号" in user_input:
        return [{
            "id": "call_002",
            "name": "book_appointment",
            "args": {"hospital": "北京儿童医院", "date": "2026-09-01", "department": "儿科"},
        }]
    elif "BMI" in user_input or "体重指数" in user_input:
        return [{
            "id": "call_003",
            "name": "calculate_bmi",
            "args": {"weight_kg": 70, "height_m": 1.75},
        }]
    return []


# ──────────────────────────────────────────────
# Agent 工具调用循环
# ──────────────────────────────────────────────

class FunctionCallingAgent:
    """
    Function Calling Agent

    核心循环（ReAct 模式）：
    1. 接收用户输入
    2. LLM 决策调用哪些工具
    3. 执行工具，拿到结果
    4. 将结果反馈给 LLM
    5. LLM 基于结果生成最终回复（或继续调用工具）
    6. 返回最终回复
    """

    def __init__(self, tools: List[ToolDefinition]):
        self._tools: Dict[str, ToolDefinition] = {t.name: t for t in tools}
        self._call_log: List[Dict] = []

    def get_tool_schemas(self) -> List[Dict]:
        """生成传给 LLM 的工具 schema 列表"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def execute_tool(self, tool_name: str, args: Dict) -> str:
        """执行工具调用"""
        tool = self._tools.get(tool_name)
        if tool is None:
            return json.dumps({"error": f"工具不存在: {tool_name}"})

        try:
            result = tool.handler(**args)
            self._call_log.append({
                "tool": tool_name,
                "args": args,
                "result": result,
            })
            return result
        except Exception as e:
            error = f"工具执行失败: {e}"
            self._call_log.append({
                "tool": tool_name,
                "args": args,
                "error": error,
            })
            return json.dumps({"error": error})

    async def run(self, user_input: str) -> str:
        """
        执行 Agent 循环

        1. LLM 决策 → tool_calls
        2. 逐个执行工具
        3. 收集 ToolMessage
        4. LLM 基于结果生成回复
        """
        print(f"  [Agent] 用户输入: {user_input}")

        # Step 1: LLM 决策调用哪些工具
        tool_calls = mock_llm_tool_calls(user_input)

        if not tool_calls:
            # 无需调用工具，直接回复
            return f"我理解您的问题，但目前没有合适的工具来处理。请换个问法。"

        # Step 2: 执行工具调用
        tool_results: List[Dict] = []
        for call in tool_calls:
            print(f"  [Agent] 调用工具: {call['name']}(args={call['args']})")
            result = self.execute_tool(call["name"], call["args"])
            print(f"  [Tool] 结果: {result}")

            tool_results.append({
                "tool_call_id": call["id"],
                "name": call["name"],
                "result": result,
            })

        # Step 3: LLM 基于工具结果生成最终回复（Mock）
        final_response = self._mock_final_response(user_input, tool_results)
        return final_response

    def _mock_final_response(self, user_input: str, tool_results: List[Dict]) -> str:
        """模拟 LLM 基于工具结果生成回复"""
        responses = []
        for tr in tool_results:
            result = json.loads(tr["result"])
            if tr["name"] == "query_vaccine":
                responses.append(
                    f"根据查询结果，{result.get('vaccine', '')}疫苗的接种程序为："
                    f"{result.get('schedule', '')}，共{result.get('doses', 0)}剂。"
                )
            elif tr["name"] == "book_appointment":
                responses.append(
                    f"已为您预约{result.get('hospital', '')}{result.get('department', '')}，"
                    f"日期：{result.get('date', '')}，预约号：{result.get('appointment_id', '')}。"
                )
            elif tr["name"] == "calculate_bmi":
                responses.append(
                    f"您的BMI为{result.get('bmi', '')}，属于{result.get('category', '')}范围。"
                )
        return " ".join(responses)

    def get_call_log(self) -> List[Dict]:
        return self._call_log


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("Function Calling Demo")
    print("=" * 60)

    agent = FunctionCallingAgent(TOOLS)

    # 打印工具列表
    print(f"\n已注册工具:")
    for schema in agent.get_tool_schemas():
        print(f"  - {schema['function']['name']}: {schema['function']['description']}")

    test_cases = [
        "6个月的宝宝要打乙肝疫苗吗？",
        "帮我预约北京儿童医院下周日的门诊",
        "帮我算一下BMI，体重70公斤身高1.75米",
    ]

    for user_input in test_cases:
        print(f"\n{'─' * 50}")
        response = await agent.run(user_input)
        print(f"  [Final] {response}")

    # 打印调用日志
    print(f"\n{'─' * 50}")
    print("工具调用日志:")
    for entry in agent.get_call_log():
        print(f"  {entry['tool']}({entry['args']}) → {entry['result'][:60]}")


if __name__ == "__main__":
    asyncio.run(main())

"""
意图识别 (Intent Recognition)
============================

核心概念：
  用户输入自然语言后，Agent 需要先判断"用户想做什么"，再决定走哪条处理链路。
  意图识别是 Agent 系统的"入口分诊台"，识别结果直接决定后续路由。

实现方式（由浅到深）：
  1. 规则匹配：关键词 + 正则，简单场景可用，零延迟
  2. 小模型分类：Fine-tuned BERT / text2vec 相似度匹配
  3. LLM 结构化输出：让大模型直接输出 JSON，带意图标签 + 置信度 + 槽位

生产实践：
  - 先走规则（快、免费），规则未命中再走 LLM（准、贵）
  - 输出必须包含置信度，低置信度时走兜底/人工
  - 槽位抽取与意图识别通常一起做，减少一次 LLM 调用

面试话术：
  "我们的意图识别采用两级策略：第一级用关键词正则做快速匹配，
   覆盖 80% 的高频意图；第二级对未命中的输入调用 LLM 做 few-shot 分类，
   输出 intent + confidence + slots 的结构化 JSON。
   当 confidence < 0.7 时自动降级到通用闲聊 Agent，避免误路由。"
"""

import re
import json
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────

@dataclass
class IntentResult:
    """意图识别结果"""
    intent: str                        # 意图标签，如 "query_vaccine"
    confidence: float                  # 置信度 0~1
    slots: Dict[str, Any] = field(default_factory=dict)  # 槽位，如 {"vaccine": "乙肝", "age": "6个月"}
    raw_text: str = ""                 # 原始用户输入
    source: str = "rule"               # 识别来源: rule / llm


# ──────────────────────────────────────────────
# 第一级：基于规则的意图识别
# ──────────────────────────────────────────────

# 意图 → 关键词模式映射
RULE_PATTERNS: Dict[str, List[str]] = {
    "query_vaccine": [
        r"疫苗|接种|打针|乙肝|卡介苗|脊灰|百白破",
    ],
    "query_feeding": [
        r"喂养|辅食|母乳|奶粉|断奶|添加|吃|喝",
    ],
    "query_development": [
        r"发育|身高|体重|翻身|爬|坐|走|说话|里程碑",
    ],
    "book_appointment": [
        r"预约|挂号|排队|门诊|体检",
    ],
}

# 槽位正则：从用户输入中提取结构化参数
SLOT_PATTERNS: Dict[str, str] = {
    "vaccine": r"(乙肝|卡介苗|脊灰|百白破|麻腮风|流脑|乙脑|甲肝|HPV|流感|水痘)",
    "age":     r"(\d+)\s*(个?月|岁)",
    "date":    r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)",
}


def rule_based_intent(text: str) -> Optional[IntentResult]:
    """基于关键词规则的意图识别（快速路径）"""
    for intent, patterns in RULE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                # 同时提取槽位
                slots: Dict[str, Any] = {}
                for slot_name, slot_pattern in SLOT_PATTERNS.items():
                    m = re.search(slot_pattern, text)
                    if m:
                        slots[slot_name] = m.group(1)

                # 规则匹配的置信度固定为 0.85（因为没有语义理解，给个中等偏高值）
                return IntentResult(
                    intent=intent,
                    confidence=0.85,
                    slots=slots,
                    raw_text=text,
                    source="rule",
                )
    return None


# ──────────────────────────────────────────────
# 第二级：基于 LLM 的意图识别（Few-shot）
# ──────────────────────────────────────────────

INTENT_LLM_PROMPT = """你是一个意图识别助手。请分析用户输入，返回 JSON 格式结果。

支持的意图列表：
- query_vaccine: 查询疫苗相关信息
- query_feeding: 查询喂养/饮食建议
- query_development: 查询生长发育指标
- book_appointment: 预约挂号/门诊
- chitchat: 闲聊/其他

示例：
输入: "6个月大的宝宝要打什么疫苗"
输出: {{"intent": "query_vaccine", "confidence": 0.95, "slots": {{"age": "6个月"}}}}

输入: "宝宝不爱吃辅食怎么办"
输出: {{"intent": "query_feeding", "confidence": 0.90, "slots": {{}}}}

输入: "今天天气真好"
输出: {{"intent": "chitchat", "confidence": 0.80, "slots": {{}}}}

现在请分析以下输入：
输入: "{user_input}"
输出:"""


async def llm_based_intent(
    text: str,
    llm_client=None,
) -> IntentResult:
    """
    基于 LLM 的意图识别（慢速路径，规则未命中时调用）

    在实际项目中，llm_client 是 OpenAI / DashScope 等 LLM SDK 客户端。
    这里用 Mock 模拟，面试时讲清楚调用链路即可。
    """
    prompt = INTENT_LLM_PROMPT.format(user_input=text)

    if llm_client is not None:
        # 真实调用：response = await llm_client.chat.completions.create(...)
        # content = response.choices[0].message.content
        pass

    # Mock：模拟 LLM 返回的 JSON
    mock_responses = {
        "宝宝最近总是哭闹": {
            "intent": "query_feeding",
            "confidence": 0.72,
            "slots": {"symptom": "哭闹"},
        },
        "你好呀": {
            "intent": "chitchat",
            "confidence": 0.88,
            "slots": {},
        },
    }

    # 模糊匹配
    for key, resp in mock_responses.items():
        if key in text:
            return IntentResult(
                intent=resp["intent"],
                confidence=resp["confidence"],
                slots=resp["slots"],
                raw_text=text,
                source="llm",
            )

    # 兜底
    return IntentResult(
        intent="chitchat",
        confidence=0.5,
        slots={},
        raw_text=text,
        source="llm",
    )


# ──────────────────────────────────────────────
# 两级策略组合
# ──────────────────────────────────────────────

async def recognize_intent(text: str, llm_client=None) -> IntentResult:
    """
    生产级意图识别：规则优先 → LLM 兜底

    调用链路：
      1. 先走 rule_based_intent（延迟 <1ms，免费）
      2. 规则未命中 → 走 llm_based_intent（延迟 200~500ms，收费）
      3. 最终返回 IntentResult
    """
    # 第一级：规则匹配
    result = rule_based_intent(text)
    if result is not None:
        return result

    # 第二级：LLM 匹配
    return await llm_based_intent(text, llm_client)


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    test_cases = [
        "6个月大的宝宝要打乙肝疫苗吗？",
        "宝宝不爱吃辅食怎么办",
        "7个月的宝宝身高体重标准是多少",
        "帮我预约下周三的儿童体检",
        "今天天气真好",
    ]

    print("=" * 60)
    print("意图识别 Demo")
    print("=" * 60)

    for text in test_cases:
        result = await recognize_intent(text)
        print(f"\n输入: {text}")
        print(f"  意图: {result.intent}")
        print(f"  置信度: {result.confidence}")
        print(f"  槽位: {result.slots}")
        print(f"  来源: {result.source}")

        # 低置信度告警
        if result.confidence < 0.7:
            print(f"  ⚠️ 置信度低于阈值(0.7)，建议降级到通用 Agent")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

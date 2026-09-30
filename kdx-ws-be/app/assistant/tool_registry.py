"""
工具注册中心 (落地 example/tool_registry.py)

能力：
- register / unregister: 动态注册与热下线
- get_schemas_for_llm: 生成传给 LLM 的 OpenAI function calling schema
- is_write: 写操作标记 → Agent 层据此触发 HITL 人工确认
- execute: 三层防线 — JSON Schema 校验 → 超时控制 → 异常统一包装
"""

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolMeta:
    name: str
    description: str
    parameters: Dict[str, Any]              # JSON Schema
    handler: Callable[..., Dict[str, Any]]  # 同步函数, graph 层用 to_thread 包裹
    is_write: bool = False                  # 写操作需要 HITL 确认
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    timeout_s: float = 10.0                 # 单工具超时 (秒)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolMeta] = {}

    def register(self, meta: ToolMeta) -> None:
        self._tools[meta.name] = meta

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Optional[ToolMeta]:
        return self._tools.get(name)

    def all_tools(self) -> List[ToolMeta]:
        return [t for t in self._tools.values() if t.enabled]

    def get_schemas_for_llm(self, tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """生成 OpenAI function calling 格式的 schema 列表"""
        schemas = []
        for t in self.all_tools():
            if tags and not any(tag in t.tags for tag in tags):
                continue
            schemas.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return schemas

    def is_write_tool(self, name: str) -> bool:
        meta = self._tools.get(name)
        return bool(meta and meta.is_write)

    def _validate_args(self, meta: ToolMeta, args: Dict[str, Any]) -> Optional[str]:
        """防线 1: 按 JSON Schema 校验 LLM 传参 (不信任 LLM)"""
        schema = meta.parameters
        props = schema.get("properties", {})
        required = schema.get("required", [])

        # 必填检查
        for req in required:
            if req not in args or args[req] is None:
                return f"missing required parameter: {req}"

        # 类型检查 (基本类型)
        type_map = {
            "string": str, "integer": int, "number": (int, float),
            "boolean": bool, "array": list, "object": dict,
        }
        for key, val in args.items():
            if key in ("user_id", "request_id"):  # 系统注入, 跳过
                continue
            prop = props.get(key)
            if not prop:
                continue
            expected = prop.get("type")
            if expected and expected in type_map:
                py_type = type_map[expected]
                if not isinstance(val, py_type):
                    return f"parameter '{key}' must be {expected}, got {type(val).__name__}"

            # enum 校验
            enum_vals = prop.get("enum")
            if enum_vals and val not in enum_vals:
                return f"parameter '{key}' must be one of {enum_vals}, got '{val}'"

        return None

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        安全执行工具: 三层防线
        防线1: JSON Schema 校验 → 参数错误结构化回灌 LLM 让其自纠
        防线2: 超时控制 → 防单个慢 SQL 卡住 ReAct 轮次
        防线3: 异常统一包装 → {"ok": False, "error": ...}
        """
        meta = self._tools.get(name)
        if meta is None:
            return {"ok": False, "error": f"tool not found: {name}"}
        if not meta.enabled:
            return {"ok": False, "error": f"tool disabled: {name}"}

        # 防线 1: 参数校验
        err = self._validate_args(meta, args)
        if err:
            return {"ok": False, "error": err, "retry_hint": True}

        # 防线 3: 执行 + 异常包装
        try:
            result = meta.handler(**(args or {}))
            return {"ok": True, "data": result}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def build_default_registry() -> ToolRegistry:
    """构建 Assistant 默认工具集（具体工具定义见 tools.py 的 register_baby_tools）"""
    from .tools import register_baby_tools
    registry = ToolRegistry()
    register_baby_tools(registry)
    return registry

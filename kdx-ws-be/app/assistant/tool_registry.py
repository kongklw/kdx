"""
工具注册中心 (落地 example/tool_registry.py)

能力：
- register / unregister: 动态注册与热下线
- get_schemas_for_llm: 生成传给 LLM 的 OpenAI function calling schema
- is_write: 写操作标记 → Agent 层据此触发 HITL 人工确认
- execute: 带异常包装的安全执行
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

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """安全执行工具：异常统一包装为 {"ok": False, "error": ...}"""
        meta = self._tools.get(name)
        if meta is None:
            return {"ok": False, "error": f"tool not found: {name}"}
        if not meta.enabled:
            return {"ok": False, "error": f"tool disabled: {name}"}
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

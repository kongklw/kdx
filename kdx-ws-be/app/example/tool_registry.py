"""
工具注册中心 (Tool Registry Center)
=====================================

核心概念：
  Agent 系统中可能有几十上百个工具，需要一个统一的注册中心来管理：
  - 注册：工具上线时注册到中心
  - 发现：Agent 运行时动态查询可用工具
  - 版本管理：同一工具可以有多个版本
  - 权限控制：不同角色可见不同工具
  - 热更新：不停机新增/下线工具

与 LangChain 的关系：
  LangChain 的 @tool 装饰器 + tools 列表是最简形式。
  生产环境需要注册中心来动态管理，而非硬编码 tools 列表。

面试话术：
  "我们的工具注册中心支持动态注册和发现。
   每个工具注册时声明 name、description、参数 schema、所需权限、版本号。
   Agent 运行时根据用户角色和任务上下文，从注册中心动态拉取可用工具列表，
   传给 LLM 做 Function Calling。
   新增工具不需要改 Agent 代码，只需注册到中心，
   热更新机制确保已运行的 Agent 能感知到新工具。"
"""

import json
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime


# ──────────────────────────────────────────────
# 工具元数据
# ──────────────────────────────────────────────

@dataclass
class ToolMeta:
    """工具元数据"""
    name: str
    description: str
    parameters: Dict[str, Any]          # JSON Schema
    handler: Optional[Callable] = None # 实际执行函数
    version: str = "1.0.0"
    required_role: str = "user"        # 所需权限: user / admin / doctor
    enabled: bool = True               # 是否启用
    registered_at: str = ""
    tags: List[str] = field(default_factory=list)  # 标签，用于分类筛选


# ──────────────────────────────────────────────
# 工具注册中心
# ──────────────────────────────────────────────

class ToolRegistry:
    """
    工具注册中心

    核心能力：
    1. register()  - 注册工具
    2. unregister() - 注销工具
    3. discover()  - 按条件发现工具
    4. get()       - 获取单个工具
    5. execute()   - 执行工具
    6. 热更新：注册/注销立即生效，不影响已运行流程
    """

    def __init__(self):
        self._tools: Dict[str, ToolMeta] = {}
        self._version_history: Dict[str, List[ToolMeta]] = {}
        self._listeners: List[Callable] = []  # 工具变更监听器

    def register(self, meta: ToolMeta) -> bool:
        """注册工具"""
        if not meta.registered_at:
            meta.registered_at = datetime.now().isoformat()

        # 版本历史
        self._version_history.setdefault(meta.name, []).append(meta)

        self._tools[meta.name] = meta
        print(f"  [Registry] 工具注册: {meta.name} v{meta.version} (role={meta.required_role})")
        self._notify_listeners("register", meta.name)
        return True

    def unregister(self, name: str) -> bool:
        """注销工具（热下线）"""
        if name in self._tools:
            del self._tools[name]
            print(f"  [Registry] 工具下线: {name}")
            self._notify_listeners("unregister", name)
            return True
        return False

    def get(self, name: str) -> Optional[ToolMeta]:
        """获取单个工具"""
        return self._tools.get(name)

    def discover(
        self,
        role: str = "user",
        tags: Optional[List[str]] = None,
    ) -> List[ToolMeta]:
        """
        发现可用工具

        1. 按角色过滤（权限控制）
        2. 按标签过滤（上下文筛选）
        3. 只返回 enabled 的工具
        """
        results = []
        for tool in self._tools.values():
            # 权限过滤
            if not self._has_permission(role, tool.required_role):
                continue
            # 启用过滤
            if not tool.enabled:
                continue
            # 标签过滤
            if tags and not any(t in tool.tags for t in tags):
                continue
            results.append(tool)
        return results

    def get_schemas_for_llm(
        self,
        role: str = "user",
        tags: Optional[List[str]] = None,
    ) -> List[Dict]:
        """生成传给 LLM 的工具 schema 列表"""
        tools = self.discover(role=role, tags=tags)
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    def execute(self, name: str, args: Dict) -> str:
        """执行工具"""
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"工具不存在: {name}"})
        if not tool.enabled:
            return json.dumps({"error": f"工具已禁用: {name}"})
        if tool.handler is None:
            return json.dumps({"error": f"工具无执行函数: {name}"})
        try:
            result = tool.handler(**args)
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"执行失败: {e}"}, ensure_ascii=False)

    def add_listener(self, listener: Callable):
        """添加工具变更监听器（热更新通知）"""
        self._listeners.append(listener)

    def _has_permission(self, user_role: str, required_role: str) -> bool:
        """权限校验"""
        role_hierarchy = {"user": 0, "doctor": 1, "admin": 2}
        user_level = role_hierarchy.get(user_role, 0)
        required_level = role_hierarchy.get(required_role, 0)
        return user_level >= required_level

    def _notify_listeners(self, action: str, tool_name: str):
        """通知监听器"""
        for listener in self._listeners:
            listener(action, tool_name)

    def list_all(self) -> List[Dict]:
        """列出所有工具状态"""
        return [
            {
                "name": t.name,
                "version": t.version,
                "enabled": t.enabled,
                "role": t.required_role,
                "tags": t.tags,
            }
            for t in self._tools.values()
        ]


# ──────────────────────────────────────────────
# 工具实现
# ──────────────────────────────────────────────

def query_vaccine(vaccine_name: str, age_months: int = 0) -> str:
    return json.dumps({"vaccine": vaccine_name, "schedule": "出生时、1月、6月", "doses": 3}, ensure_ascii=False)

def book_appointment(hospital: str, date: str, department: str = "儿科") -> str:
    return json.dumps({"success": True, "hospital": hospital, "date": date}, ensure_ascii=False)

def prescribe_medication(medicine: str, dosage: str) -> str:
    """医生开处方（需要 doctor 权限）"""
    return json.dumps({"prescription": medicine, "dosage": dosage}, ensure_ascii=False)

def manage_system(config_key: str, config_value: str) -> str:
    """系统管理（需要 admin 权限）"""
    return json.dumps({"updated": f"{config_key}={config_value}"}, ensure_ascii=False)


# ──────────────────────────────────────────────
# 运行示例
# ──────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("工具注册中心 Demo")
    print("=" * 60)

    registry = ToolRegistry()

    # 注册工具
    print("\n1. 注册工具:")
    registry.register(ToolMeta(
        name="query_vaccine",
        description="查询疫苗接种信息",
        parameters={"type": "object", "properties": {"vaccine_name": {"type": "string"}}},
        handler=query_vaccine,
        required_role="user",
        tags=["medical", "vaccine"],
    ))
    registry.register(ToolMeta(
        name="book_appointment",
        description="预约门诊挂号",
        parameters={"type": "object", "properties": {"hospital": {"type": "string"}, "date": {"type": "string"}}},
        handler=book_appointment,
        required_role="user",
        tags=["appointment"],
    ))
    registry.register(ToolMeta(
        name="prescribe_medication",
        description="开具处方药（仅医生可用）",
        parameters={"type": "object", "properties": {"medicine": {"type": "string"}, "dosage": {"type": "string"}}},
        handler=prescribe_medication,
        required_role="doctor",
        tags=["medical", "prescription"],
    ))
    registry.register(ToolMeta(
        name="manage_system",
        description="系统配置管理（仅管理员可用）",
        parameters={"type": "object", "properties": {"config_key": {"type": "string"}, "config_value": {"type": "string"}}},
        handler=manage_system,
        required_role="admin",
        tags=["system"],
    ))

    # 按角色发现工具
    print("\n2. 普通用户可用工具:")
    user_tools = registry.discover(role="user")
    for t in user_tools:
        print(f"  - {t.name}: {t.description}")

    print("\n3. 医生可用工具:")
    doctor_tools = registry.discover(role="doctor")
    for t in doctor_tools:
        print(f"  - {t.name}: {t.description}")

    print("\n4. 管理员可用工具:")
    admin_tools = registry.discover(role="admin")
    for t in admin_tools:
        print(f"  - {t.name}: {t.description}")

    # 按标签筛选
    print("\n5. 医疗类工具(user视角):")
    medical_tools = registry.discover(role="user", tags=["medical"])
    for t in medical_tools:
        print(f"  - {t.name}")

    # 执行工具
    print("\n6. 执行工具:")
    result1 = registry.execute("query_vaccine", {"vaccine_name": "乙肝", "age_months": 6})
    print(f"  query_vaccine → {result1}")

    # 热下线
    print("\n7. 热下线 book_appointment:")
    registry.unregister("book_appointment")
    result2 = registry.execute("book_appointment", {"hospital": "儿童医院", "date": "2026-09-01"})
    print(f"  book_appointment → {result2}")

    # 权限拒绝
    print("\n8. 权限拒绝（user尝试调用 admin 工具）:")
    schemas = registry.get_schemas_for_llm(role="user")
    tool_names = [s["function"]["name"] for s in schemas]
    print(f"  user 可见的工具: {tool_names}")
    print(f"  manage_system 在列表中? {'manage_system' in tool_names}")

    # 全量状态
    print(f"\n9. 全量工具状态:")
    for t in registry.list_all():
        print(f"  {t}")


if __name__ == "__main__":
    asyncio.run(main())

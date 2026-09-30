"""WebSocket 基础设施 (跨接口复用): 配置 / 连接管理 / 鉴权 / 协议工具。

设计原则:
- 单一职责: 每个模块只解决一类问题 (配置/连接/鉴权/协议)
- 依赖单向: protocol ← auth ← connection_manager ← 接口, 无环依赖
- 接口层只写业务分发, WS 生产逻辑全部复用本包, 新增 WS 接口零重复
"""
from .config import WSConfig, get_ws_config
from .connection_manager import ConnectionManager, connection_manager
from .auth import authenticate, extract_token, check_origin
from .protocol import (
    CloseCode,
    IdleTimeout,
    MessageTooBig,
    safe_send_json,
    receive_message,
    parse_payload,
)

__all__ = [
    "WSConfig", "get_ws_config",
    "ConnectionManager", "connection_manager",
    "authenticate", "extract_token", "check_origin",
    "CloseCode", "IdleTimeout", "MessageTooBig",
    "safe_send_json", "receive_message", "parse_payload",
]

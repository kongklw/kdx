"""WebSocket 线路协议工具: 关闭码 / 异常 / 安全下发 / 接收与解析。

纯传输层关注点, 不含业务语义, 所有 WS 接口复用。
"""
import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import WebSocket


class CloseCode:
    """统一关闭码 (RFC6455 标准 + 业务自定义)。"""
    NORMAL = 1000              # 正常关闭
    GOING_AWAY = 1001          # 端点离开 / 空闲踢出
    POLICY_VIOLATION = 1008    # 策略违规 (超连接数 / Origin 非法)
    MESSAGE_TOO_BIG = 1009     # 帧过大
    INTERNAL_ERROR = 1011      # 服务端内部错误
    AUTH_FAILED = 4401         # 鉴权失败 (业务自定义)


class IdleTimeout(Exception):
    """接收超时: 长时间无消息, 需踢出以清理半开/僵尸连接。"""


class MessageTooBig(Exception):
    """帧超过 max_message_size。

    说明: 此处为下游保护 (帧已读入内存); 真正的帧级上限需在 uvicorn 启动参数
    --ws-max-size 设置, 否则超大帧仍会先占用内存再被拒绝。
    """
    def __init__(self, size: int):
        self.size = size
        super().__init__(f"message too big: {size}B")


async def safe_send_json(ws: WebSocket, payload: Dict[str, Any]) -> bool:
    """安全下发: 连接已断/对端异常时静默, 返回是否成功。

    防止 send_json 在连接半关闭时抛出 RuntimeError/RuntimeError 而中断业务循环。
    """
    try:
        await ws.send_json(payload)
        return True
    except Exception:
        return False


async def receive_message(ws: WebSocket, idle_timeout: int) -> Dict[str, Any]:
    """阻塞接收一条原始消息; 超过 idle_timeout 抛 IdleTimeout (由调用方决定关闭)。"""
    try:
        return await asyncio.wait_for(ws.receive(), timeout=idle_timeout)
    except asyncio.TimeoutError:
        raise IdleTimeout()


def parse_payload(message: Dict[str, Any], max_size: int) -> Optional[Dict[str, Any]]:
    """从 receive() 结果提取并解析文本 JSON 帧。

    返回:
      dict  —— 文本 JSON 对象帧
      None  —— 二进制帧/空帧, 由调用方按 message["bytes"] 处理
    抛:
      MessageTooBig —— 帧超限
      ValueError    —— 非 JSON 或非对象
    """
    text = message.get("text")
    data = message.get("bytes")
    # 既没有 云因输入 data 也没有文字输入 text 直接返回None
    if text is None and data is None:
        return None

    if text is not None:
        # 如果有文字输入，判断文字输入长度
        size = len(text) if text is not None else len(data)
        if size > max_size:
            raise MessageTooBig(size)
        decoded = json.loads(text)
        if not isinstance(decoded, dict):
            raise ValueError("payload must be a JSON object")
        return decoded

    else:
        return None



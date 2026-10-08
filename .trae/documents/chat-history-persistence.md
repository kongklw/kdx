# AI 对话历史持久化方案

## Context

当前 AiEntrance 页面刷新或重新登录后，`messages` 数组重置为空，用户看不到之前的对话记录。用户希望像豆包一样，刷新/重登后仍能看到历史对话和结果。

## 方案：Redis 存储 + 页面加载时拉取

### 1. 后端：聊天历史服务

**新建 `app/services/chat_history_service.py`**
- 异步 Redis 客户端（复用 `resilience.py` 的 `redis.asyncio.from_url` 模式 + 降级到内存）
- `save_message(user_id, msg_dict)` — RPUSH JSON 到 `kdx:chat:{user_id}`，TTL 7 天
- `get_recent(user_id, limit=50)` — LRANGE + JSON 反序列化，返回最近 N 条消息
- Redis 不可用时降级到进程内列表（与 RateLimiter 同模式）

**修改 `app/ws/app_ai_entrance.py`**
- 在 `handle_query()` 发送 `query_received` 后：保存用户消息 `{role:"user", text:query, request_id, source, created_at}`
- 在 `send_agent_event` 回调中拦截 `query_done`/`answer_done`：保存 AI 消息 `{role:"ai", text, toolEvents, request_id, created_at}`
- 关键：在 `_done_payload` 累积的最终状态时保存，不是每次事件都保存

**新增 API 路由 `app/api/v1/ai_chat.py`**
- `GET /api/v1/ai/chat-history?limit=50` — 返回当前用户最近 N 条聊天记录
- 复用现有 `get_current_user` 依赖注入

### 2. 前端：加载历史

**修改 `src/views/mobile/AiEntrance.vue`**
- `mounted()` 中先调 HTTP API 拉取最近 50 条历史 → 填充 `this.messages` → 再 `connect()` WS
- 历史消息标记 `fromHistory: true`（不显示流式动画，直接渲染最终态）
- 历史消息的 `toolEvents`/`confirm` 从 JSON 反序列化恢复

**新增 `src/api/ai.js`**
- `getChatHistory(limit=50)` — GET `/dev-api/api/v1/ai/chat-history`

### 3. 数据模型

Redis 存储格式（key: `kdx:chat:{user_id}`，list type）：
```json
{
  "role": "user|ai",
  "text": "查询或回答文本",
  "tool_events": [{"name":"add_feed_milk","brief":"150ml","ok":true}],
  "request_id": "req-xxx",
  "source": "text|voice",
  "created_at": "2026-10-08T10:30:00"
}
```

### 4. 关键文件

| 文件 | 操作 |
|---|---|
| `app/services/chat_history_service.py` | 新建 |
| `app/api/v1/ai_chat.py` | 新建 |
| `app/api/v1/__init__.py` | 注册路由 |
| `app/ws/app_ai_entrance.py` | 在 handle_query + emit 回调中保存消息 |
| `src/views/mobile/AiEntrance.vue` | mounted 加载历史 |
| `src/api/ai.js` | 新建 API 函数 |

### 5. 验证

1. 发几条对话（文字 + 确认）→ 刷新页面 → 历史消息全部出现
2. 退出登录 → 重新登录 → 历史仍在
3. 多用户隔离：user 3 看不到 user 1 的历史
4. Redis 断开时不影响正常对话（降级内存）

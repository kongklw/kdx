# AI 聊天历史持久化 — 实现逻辑

## 目标

用户在 AI 对话框中的所有查询和 AI 回复必须持久化，无论退出账号、刷新页面、后端重启，历史记录都不丢失。

## 架构总览

```
前端 AiEntrance.vue                  后端 (FastAPI :8001)
┌─────────────────┐                 ┌──────────────────────────┐
│  mounted()      │                 │  app_ai_entrance.py       │
│  ├ loadHistory()│──HTTP GET──►   │  (WebSocket 入口)          │
│  │  GET /api/v1/ │                │  ├ 用户消息 → save_message│
│  │  ai/chat-     │◄──JSON──       │  ├ answer_done → save     │
│  │  history      │                │  ├ confirm_req → save     │
│  └ connect()    │──WebSocket──►  │  └ query_error → save     │
│                  │                 │                          │
│  messages[]      │                 │  ai_chat.py              │
│  (历史+实时)     │                 │  GET /api/v1/ai/chat-hist │
└─────────────────┘                 └──────────┬───────────────┘
                                               │
                                    ┌──────────▼───────────────┐
                                    │  ChatHistoryService       │
                                    │  (单例, Redis list)       │
                                    │  key: kdx:chat:{user_id} │
                                    │  TTL: 7天, MAX: 500条    │
                                    └──────────┬───────────────┘
                                               │
                                    ┌──────────▼───────────────┐
                                    │  Redis (47.95.15.228:6379)│
                                    │  DB: 0 (REDIS_CACHE_DB)  │
                                    └──────────────────────────┘
```

## 后端实现

### 1. ChatHistoryService (`app/services/chat_history_service.py`)

核心存储服务，单例模式。

**存储方式**: Redis list，每条消息 JSON 序列化后 `RPUSH` 到 `kdx:chat:{user_id}`。

**关键设计**:
- 按 `user_id` 隔离，不同用户历史互不干扰
- TTL 7 天自动过期（每次写入续期）
- 每用户最多 500 条，超出自动 `LTRIM` 截断旧消息
- Redis 不可用时降级为进程内 `dict`，30 秒后自动重试连接

**核心方法**:
```python
save_message(user_id, msg)  # 追加一条消息
get_recent(user_id, limit)  # 返回最近 N 条 (时间正序)
```

**Redis 连接初始化**:
```python
# 首次调用时传入 settings.redis_url (由 config.py 从 .env 构建)
ChatHistoryService.get_instance(settings.redis_url)
# 后续无参调用返回已缓存单例
ChatHistoryService.get_instance()
```

> **修复记录**: 原实现用 `os.getenv("REDIS_URL")` 查找连接地址，但 `.env` 只有 `REDIS_HOST`/`REDIS_PASSWORD` 等分离变量，导致回退到 `localhost:6379`，连不上远程 Redis，所有消息存在进程内存中，后端重启即丢失。

### 2. HTTP API (`app/api/ai_chat.py`)

```
GET /api/v1/ai/chat-history?limit=50
Authorization: Bearer <JWT>
```

- JWT 鉴权 (`require_user_id`)，提取 `user_id` 隔离历史
- 返回 `{code: 200, data: {messages: [...]}, msg: "ok"}`

### 3. WebSocket 入口保存 (`app/ws/app_ai_entrance.py`)

在 `send_agent_event` 回调中拦截关键事件持久化:

| 事件 | 保存内容 |
|------|---------|
| 用户发送 `query` | `{role: "user", text, request_id, source}` |
| `answer_done` | `{role: "ai", text, tool_events, request_id}` |
| `confirmation_request` | `{role: "ai", text:"", confirm:{...}, request_id}` |
| `query_error` | `{role: "ai", text:"⚠️ 错误信息", request_id}` |

> 用户消息在 `handle_query()` 中保存，AI 消息在 `send_agent_event()` 回调中保存，确保每次对话都有 user+ai 消息对。

## 前端实现

### 1. API 封装 (`src/api/ai.js`)

```javascript
getChatHistory(limit = 50)
  → GET /prod-ai/api/v1/ai/chat-history  (走 FastAPI 代理)
```

`baseURL: '/prod-ai'` 覆盖默认的 `/dev-api`(Django)，确保请求打到 FastAPI 后端。

### 2. 历史加载 (`src/views/mobile/AiEntrance.vue`)

```javascript
mounted() {
    this.loadHistory().finally(() => this.connect())
}
```

- 组件挂载时先拉取历史，再建立 WebSocket 连接
- 历史消息标记 `fromHistory: true`，与实时消息区分
- 历史 `confirm` 卡片标记过期，不渲染按钮（会话已结束无法确认）
- 过滤空消息（无文本且无工具调用的 AI 消息）

### 3. 代理配置

**开发环境** (`vue.config.js`):
```javascript
'/prod-ai': {
    target: 'http://localhost:8001',
    ws: true,
    pathRewrite: { '^/prod-ai': '' }
}
```

**生产环境** (`compose/nginx/default.conf`):
```nginx
location /prod-ai/ {
    proxy_pass http://fastapi/;
}
location /prod-ai/ws/ {
    proxy_pass http://fastapi/ws/;
}
```

## 持久化保障

| 场景 | 保障方式 |
|------|---------|
| 刷新页面 | `mounted()` 重新调用 `loadHistory()` 从 Redis 拉取 |
| 退出再登录 | 历史按 `user_id` 存储，JWT 中的 `user_id` 不变 |
| 后端重启 | Redis 持久化，数据不受进程重启影响 |
| Redis 宕机 | 降级进程内内存 (临时)，30s 后自动重试恢复 Redis |
| 历史过期 | TTL 7 天，活跃用户每次写入自动续期 |

## 涉及文件

| 文件 | 职责 |
|------|------|
| `app/services/chat_history_service.py` | Redis 存储 + 降级 + 重试 |
| `app/api/ai_chat.py` | HTTP API 路由 |
| `app/ws/app_ai_entrance.py` | WebSocket 消息持久化 |
| `app/main.py` | 路由注册 |
| `src/api/ai.js` | 前端 API 封装 |
| `src/views/mobile/AiEntrance.vue` | 前端历史加载 + 渲染 |
| `vue.config.js` | 开发代理 `/prod-ai` |
| `compose/nginx/default.conf` | 生产代理 `/prod-ai` |

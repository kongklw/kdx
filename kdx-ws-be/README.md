# kdemo_fastapi

一个基于 FastAPI 的轻量级服务，用于承载与 `kdemo` 主项目解耦的能力（例如语音 WebSocket 代理、健康检查等），便于独立扩展、独立部署与独立扩容。

## 功能

- HTTP 健康检查：`GET /health`
- WebSocket 语音代理：`/ws/voice-agent`
  - 支持 token 校验（query 或 header）
  - 支持二进制音频分片与简单 ack

## 本地运行

在仓库根目录执行：

```bash
cd kdemo_fastapi
python -m pip install -e .
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

访问：

- `http://localhost:8002/health`

## 配置项（环境变量）

该项目会尝试加载 `kdemo/.env`（仓库根目录下的 `kdemo/.env`），并从环境变量中读取配置。

- `SECRET_KEY`：JWT 验签密钥
- `JWT_ALGORITHM`：JWT 算法，默认 `HS256`
- `VOICE_WS_ALLOW_ANON`：是否允许匿名 WebSocket，`1/true/yes` 表示允许
- `REDIS_HOST` `REDIS_PORT` `REDIS_CACHE_DB` `REDIS_PASSWORD`：构造 `redis_url`
- `MYSQL_USER` `MYSQL_PASSWORD` `DB_HOST` `DB_PORT` `MYSQL_DATABASE`：构造 `mysql_dsn`

## 项目结构（生产级别布局）

当前目录结构设计遵循“分层 + 领域可扩展”的思路：`core` 放基础能力，`api` 放 HTTP 路由，`ws` 放 WebSocket 路由与协议处理，避免所有代码堆在 `main.py`。

```text
kdemo_fastapi/
  app/
    main.py                # 应用入口：创建 FastAPI 实例、挂载路由
    api/
      health.py            # HTTP 路由（示例：健康检查）
    ws/
      voice_agent.py       # WebSocket 路由与协议处理（示例：语音代理）
    core/
      config.py            # Settings / 环境变量解析 / load_env
      security.py          # JWT 校验、token 提取
    config.py              # 兼容入口（重导出 core.config）
    security.py            # 兼容入口（重导出 core.security）
    voice_ws.py            # 兼容入口（重导出 ws.voice_agent.voice_agent_ws）
  pyproject.toml
  Dockerfile
```

## 后续如何编写（推荐方式）

### 1）新增一个 HTTP 接口

在 `app/api/` 下新建一个路由文件，例如 `app/api/baby.py`：

```python
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/baby", tags=["baby"])

@router.get("/ping")
async def ping() -> JSONResponse:
    return JSONResponse({"ok": True})
```

然后在 `app/main.py` 中挂载：

```python
from .api.baby import router as baby_router
app.include_router(baby_router)
```

### 2）新增一个 WebSocket 服务

在 `app/ws/` 下新建模块，并提供 `create_xxx_router(settings)` 工厂函数（推荐），这样可以把依赖（例如 Settings、DB/Redis 客户端）集中从入口注入，避免全局变量污染与循环依赖。

### 3）写业务逻辑的放置建议

- 纯业务规则：放在 `app/services/`（后续需要时再创建）
- 与外部系统交互：放在 `app/integrations/`（后续需要时再创建）
- 数据模型与校验：放在 `app/schemas/`（后续需要时再创建）

目标是让 `api/ws` 只做“协议层”，把业务逻辑沉到更内层的模块中，利于测试与复用。

## 生产部署建议

- 使用反向代理（Nginx/Ingress）统一 TLS、限流、超时控制
- Uvicorn/Gunicorn 多进程运行（按 CPU 核心数配置 worker）
- 使用结构化日志并接入采集（stdout -> ELK/Loki 等）
- WebSocket 建议配置心跳与最大消息大小限制


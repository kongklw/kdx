"""轻量级 Redis Checkpointer (纯社区版 Redis, 不依赖 RediSearch)

为什么不用官方 langgraph-checkpoint-redis: 官方实现依赖 RediSearch 模块 (Redis Stack),
本项目约束使用 redis:6.2 社区版 (ECS 镜像对齐), 故基于 BaseCheckpointSaver 自研。

语义与 InMemorySaver (langgraph/checkpoint/memory) 对齐:
- channel_values 按 (channel, version) 独立 blob 存储, checkpoint 本体不含 values;
- checkpoint_id 为 ISO 时间戳, 字典序最大即最新 (ZSET 等分时按成员字典序排序);
- pending writes 以 (task_id, WRITES_IDX_MAP[channel] or idx) 去重, 首写优先,
  负数特殊索引 (__resume__/__error__ 等) 始终覆盖;
- 序列化复用 BaseCheckpointSaver.serde (JsonPlusSerializer, 与 MemorySaver 一致)。

Redis 键布局 (key_prefix 默认 "kdx:ck", 与共享库其他业务隔离):
  {p}:cp:{thread}:{ns}            ZSET   member=checkpoint_id (score=0, 纯字典序)
  {p}:cp:{thread}:{ns}:{cp_id}    HASH   blob=检查点本体 / meta=元数据 / parent=父cp_id
  {p}:b:{thread}:{ns}:{ch}:{ver}  STRING channel blob ("{type}\\x00" + payload)
  {p}:w:{thread}:{ns}:{cp_id}     HASH   field="{task_id}:{idx}" value=JSON 信封

所有键带 TTL (默认 7 天, 每次 put/put_writes 刷新), 防止共享 Redis 无限膨胀。
同步/异步两套方法均实现 (graph.ainvoke 走异步, get_state 等同步 API 走同步)。
"""
import base64
import json
import logging
from typing import Any, AsyncIterator, Iterator, Optional, Sequence

import redis
import redis.asyncio
from langchain_core.runnables import RunnableConfig

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

logger = logging.getLogger(__name__)

_EMPTY_MARKER = b"empty\x00"


def _pack_blob(serde, obj: Any) -> bytes:
    t, b = serde.dumps_typed(obj)
    return t.encode() + b"\x00" + b


def _unpack_blob(serde, raw: bytes) -> Any:
    t, b = raw.split(b"\x00", 1)
    return serde.loads_typed((t.decode(), b))


class RedisCheckpointer(BaseCheckpointSaver[str]):
    """基于纯 Redis (无 RediSearch) 的 checkpointer, 语义对齐 MemorySaver。

    Args:
        redis_url: Redis 连接串 (settings.redis_url)
        key_prefix: 键前缀, 默认 "kdx:ck" (共享 Redis 命名空间隔离)
        ttl_seconds: 键过期时间, 默认 7 天 (会话记忆的保留窗口)
    """

    def __init__(self, redis_url: str, key_prefix: str = "kdx:ck",
                 ttl_seconds: int = 7 * 24 * 3600):
        super().__init__()
        self._redis_url = redis_url
        self._prefix = key_prefix
        self._ttl = ttl_seconds
        self._r: Optional[redis.Redis] = None
        self._ar: Optional[redis.asyncio.Redis] = None

    # ── 客户端 (懒创建) ──────────────────────────────────────────
    def _client(self) -> redis.Redis:
        if self._r is None:
            self._r = redis.Redis.from_url(
                self._redis_url, socket_connect_timeout=5,
                socket_timeout=5, decode_responses=False)
        return self._r

    def _aclient(self) -> redis.asyncio.Redis:
        if self._ar is None:
            self._ar = redis.asyncio.Redis.from_url(
                self._redis_url, socket_connect_timeout=5,
                socket_timeout=5, decode_responses=False)
        return self._ar

    def ping(self) -> None:
        """连通性自检 (init_graph_checkpointer 用)"""
        self._client().ping()

    # ── 键构建 ───────────────────────────────────────────────────
    def _k_idx(self, thread: str, ns: str) -> str:
        return f"{self._prefix}:cp:{thread}:{ns}"

    def _k_cp(self, thread: str, ns: str, cp_id: str) -> str:
        return f"{self._prefix}:cp:{thread}:{ns}:{cp_id}"

    def _k_blob(self, thread: str, ns: str, ch: str, ver: str) -> str:
        return f"{self._prefix}:b:{thread}:{ns}:{ch}:{ver}"

    def _k_writes(self, thread: str, ns: str, cp_id: str) -> str:
        return f"{self._prefix}:w:{thread}:{ns}:{cp_id}"

    # ── 内部: 组装 CheckpointTuple ──────────────────────────────
    def _assemble(self, thread: str, ns: str, cp_id: str, rec: dict,
                  config: Optional[RunnableConfig]) -> Optional[CheckpointTuple]:
        if not rec:
            return None
        ckpt = _unpack_blob(self.serde, rec[b"blob"])
        channel_values = {}
        r = self._client()
        pipe = r.pipeline()
        for ch, ver in ckpt.get("channel_versions", {}).items():
            pipe.get(self._k_blob(thread, ns, ch, str(ver)))
        blobs = pipe.execute()
        for ch, raw in zip(ckpt.get("channel_versions", {}).keys(), blobs):
            if raw and raw != _EMPTY_MARKER:
                channel_values[ch] = _unpack_blob(self.serde, raw)
        pending = []
        if w := r.hgetall(self._k_writes(thread, ns, cp_id)):
            for field in sorted(w):
                env = json.loads(w[field])
                pending.append((
                    env["tid"], env["c"],
                    self.serde.loads_typed((env["bt"], base64.b64decode(env["b"]))),
                ))
        parent = rec.get(b"parent", b"").decode()
        return CheckpointTuple(
            config=config or {"configurable": {
                "thread_id": thread, "checkpoint_ns": ns, "checkpoint_id": cp_id}},
            checkpoint={**ckpt, "channel_values": channel_values},
            metadata=_unpack_blob(self.serde, rec[b"meta"]),
            pending_writes=pending,
            parent_config=(
                {"configurable": {"thread_id": thread, "checkpoint_ns": ns,
                                  "checkpoint_id": parent}}
                if parent else None),
        )

    async def _aassemble(self, thread: str, ns: str, cp_id: str, rec: dict,
                         config: Optional[RunnableConfig]) -> Optional[CheckpointTuple]:
        if not rec:
            return None
        ckpt = _unpack_blob(self.serde, rec[b"blob"])
        channel_values = {}
        ar = self._aclient()
        pipe = ar.pipeline()
        for ch, ver in ckpt.get("channel_versions", {}).items():
            pipe.get(self._k_blob(thread, ns, ch, str(ver)))
        blobs = await pipe.execute()
        for ch, raw in zip(ckpt.get("channel_versions", {}).keys(), blobs):
            if raw and raw != _EMPTY_MARKER:
                channel_values[ch] = _unpack_blob(self.serde, raw)
        pending = []
        if w := await ar.hgetall(self._k_writes(thread, ns, cp_id)):
            for field in sorted(w):
                env = json.loads(w[field])
                pending.append((
                    env["tid"], env["c"],
                    self.serde.loads_typed((env["bt"], base64.b64decode(env["b"]))),
                ))
        parent = rec.get(b"parent", b"").decode()
        return CheckpointTuple(
            config=config or {"configurable": {
                "thread_id": thread, "checkpoint_ns": ns, "checkpoint_id": cp_id}},
            checkpoint={**ckpt, "channel_values": channel_values},
            metadata=_unpack_blob(self.serde, rec[b"meta"]),
            pending_writes=pending,
            parent_config=(
                {"configurable": {"thread_id": thread, "checkpoint_ns": ns,
                                  "checkpoint_id": parent}}
                if parent else None),
        )

    # ── 同步 API ────────────────────────────────────────────────
    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        r = self._client()
        if not (cp_id := get_checkpoint_id(config)):
            if not (latest := r.zrevrange(self._k_idx(thread, ns), 0, 0)):
                return None
            cp_id = latest[0].decode()
        rec = r.hgetall(self._k_cp(thread, ns, cp_id))
        if not rec:
            return None
        return self._assemble(thread, ns, cp_id, rec, config)

    def put(self, config: RunnableConfig, checkpoint: Checkpoint,
            metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        values = dict(checkpoint).pop("channel_values")  # checkpoint 本体剔除 values
        r = self._client()
        pipe = r.pipeline()
        cp_id = checkpoint["id"]
        for k, ver in new_versions.items():
            if k in values:
                pipe.set(self._k_blob(thread, ns, k, str(ver)),
                         _pack_blob(self.serde, values[k]), ex=self._ttl)
            else:
                pipe.set(self._k_blob(thread, ns, k, str(ver)),
                         _EMPTY_MARKER, ex=self._ttl)
        pipe.hset(self._k_cp(thread, ns, cp_id), mapping={
            b"blob": _pack_blob(self.serde,
                                {k: v for k, v in checkpoint.items()
                                 if k != "channel_values"}),
            b"meta": _pack_blob(self.serde,
                                get_checkpoint_metadata(config, metadata)),
            b"parent": (config["configurable"].get("checkpoint_id") or "").encode(),
        })
        pipe.expire(self._k_cp(thread, ns, cp_id), self._ttl)
        pipe.zadd(self._k_idx(thread, ns), {cp_id: 0})
        pipe.expire(self._k_idx(thread, ns), self._ttl)
        pipe.execute()
        return {"configurable": {"thread_id": thread, "checkpoint_ns": ns,
                                 "checkpoint_id": cp_id}}

    def put_writes(self, config: RunnableConfig,
                   writes: Sequence[tuple[str, Any]], task_id: str,
                   task_path: str = "") -> None:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        cp_id = config["configurable"]["checkpoint_id"]
        r = self._client()
        wkey = self._k_writes(thread, ns, cp_id)
        pipe = r.pipeline()
        changed = False
        for idx, (c, v) in enumerate(writes):
            i = WRITES_IDX_MAP.get(c, idx)
            field = f"{task_id}:{i}"
            if i >= 0 and r.hexists(wkey, field):
                continue  # 首写优先 (与 MemorySaver 一致)
            t, b = self.serde.dumps_typed(v)
            pipe.hset(wkey, field, json.dumps({
                "tid": task_id, "c": c, "p": task_path,
                "bt": t, "b": base64.b64encode(b).decode(),
            }))
            changed = True
        if changed:
            pipe.expire(wkey, self._ttl)
        pipe.execute()

    def list(self, config: Optional[RunnableConfig], *, filter=None, before=None,
             limit: Optional[int] = None) -> Iterator[CheckpointTuple]:
        """按线程列出 checkpoint (新→旧); 仅支持 thread 级 config, filter 线程内过滤"""
        if not config:
            return  # Redis 版不支持全库扫描 (MemorySaver 支持, 但本应用无需)
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        r = self._client()
        if before and (bid := get_checkpoint_id(before)):
            members = r.zrevrangebylex(self._k_idx(thread, ns),
                                       b"(" + bid.encode(), b"+")
        else:
            members = r.zrevrange(self._k_idx(thread, ns), 0, -1)
        for m in members:
            cp_id = m.decode()
            rec = r.hgetall(self._k_cp(thread, ns, cp_id))
            if not rec:
                continue
            tuple_ = self._assemble(thread, ns, cp_id, rec, None)
            if filter and not all(
                tuple_.metadata.get(k) == v for k, v in filter.items()
            ):
                continue
            if limit is not None and limit <= 0:
                return
            if limit is not None:
                limit -= 1
            yield tuple_

    def delete_thread(self, thread: str) -> None:
        r = self._client()
        for pattern in (f"{self._prefix}:cp:{thread}:*",
                        f"{self._prefix}:b:{thread}:*",
                        f"{self._prefix}:w:{thread}:*"):
            keys = list(r.scan_iter(pattern, count=200))
            if keys:
                r.delete(*keys)

    # ── 异步 API (graph.ainvoke 主路径) ─────────────────────────
    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        ar = self._aclient()
        if not (cp_id := get_checkpoint_id(config)):
            if not (latest := await ar.zrevrange(self._k_idx(thread, ns), 0, 0)):
                return None
            cp_id = latest[0].decode()
        rec = await ar.hgetall(self._k_cp(thread, ns, cp_id))
        if not rec:
            return None
        return await self._aassemble(thread, ns, cp_id, rec, config)

    async def aput(self, config: RunnableConfig, checkpoint: Checkpoint,
                   metadata: CheckpointMetadata,
                   new_versions: ChannelVersions) -> RunnableConfig:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        values = checkpoint.get("channel_values") or {}
        ar = self._aclient()
        cp_id = checkpoint["id"]
        pipe = ar.pipeline()
        for k, ver in new_versions.items():
            if k in values:
                pipe.set(self._k_blob(thread, ns, k, str(ver)),
                         _pack_blob(self.serde, values[k]), ex=self._ttl)
            else:
                pipe.set(self._k_blob(thread, ns, k, str(ver)),
                         _EMPTY_MARKER, ex=self._ttl)
        pipe.hset(self._k_cp(thread, ns, cp_id), mapping={
            b"blob": _pack_blob(self.serde,
                                {k: v for k, v in checkpoint.items()
                                 if k != "channel_values"}),
            b"meta": _pack_blob(self.serde,
                                get_checkpoint_metadata(config, metadata)),
            b"parent": (config["configurable"].get("checkpoint_id") or "").encode(),
        })
        pipe.expire(self._k_cp(thread, ns, cp_id), self._ttl)
        pipe.zadd(self._k_idx(thread, ns), {cp_id: 0})
        pipe.expire(self._k_idx(thread, ns), self._ttl)
        await pipe.execute()
        return {"configurable": {"thread_id": thread, "checkpoint_ns": ns,
                                 "checkpoint_id": cp_id}}

    async def aput_writes(self, config: RunnableConfig,
                          writes: Sequence[tuple[str, Any]], task_id: str,
                          task_path: str = "") -> None:
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        cp_id = config["configurable"]["checkpoint_id"]
        ar = self._aclient()
        wkey = self._k_writes(thread, ns, cp_id)
        pipe = ar.pipeline()
        changed = False
        for idx, (c, v) in enumerate(writes):
            i = WRITES_IDX_MAP.get(c, idx)
            field = f"{task_id}:{i}"
            if i >= 0 and await ar.hexists(wkey, field):
                continue
            t, b = self.serde.dumps_typed(v)
            pipe.hset(wkey, field, json.dumps({
                "tid": task_id, "c": c, "p": task_path,
                "bt": t, "b": base64.b64encode(b).decode(),
            }))
            changed = True
        if changed:
            pipe.expire(wkey, self._ttl)
        await pipe.execute()

    async def alist(self, config: Optional[RunnableConfig], *, filter=None,
                    before=None, limit: Optional[int] = None
                    ) -> AsyncIterator[CheckpointTuple]:
        if not config:
            return
        thread = config["configurable"]["thread_id"]
        ns = config["configurable"].get("checkpoint_ns", "")
        ar = self._aclient()
        if before and (bid := get_checkpoint_id(before)):
            members = await ar.zrevrangebylex(self._k_idx(thread, ns),
                                              b"(" + bid.encode(), b"+")
        else:
            members = await ar.zrevrange(self._k_idx(thread, ns), 0, -1)
        for m in members:
            cp_id = m.decode()
            rec = await ar.hgetall(self._k_cp(thread, ns, cp_id))
            if not rec:
                continue
            tuple_ = await self._aassemble(thread, ns, cp_id, rec, None)
            if filter and not all(
                tuple_.metadata.get(k) == v for k, v in filter.items()
            ):
                continue
            if limit is not None and limit <= 0:
                return
            if limit is not None:
                limit -= 1
            yield tuple_

    async def adelete_thread(self, thread: str) -> None:
        self.delete_thread(thread)

    # ── 版本号 (与 MemorySaver 同格式: 字典序可比较) ─────────────
    def get_next_version(self, current: Optional[str], channel: None) -> str:
        import random
        if current is None:
            current_v = 0
        elif isinstance(current, int):
            current_v = current
        else:
            current_v = int(current.split(".")[0])
        next_v = current_v + 1
        next_h = random.random()
        return f"{next_v:032}.{next_h:016}"

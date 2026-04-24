"""V1.1 · Phase 9 · AI 观察存储层。

双写策略：
1. **内存环形**（``deque(maxlen=N)``）：给 REST/WS 高频读，O(1) latest；
2. **JSONL 追加**：给审计 / 回放 / 导出，每条一行 JSON，文件位置由
   ``settings.resolve_path("data/ai_observations.jsonl")`` 决定。

两者互不阻塞 —— JSONL 写入用 ``aiofiles``。若写盘失败只告警、不影响内存环形。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from pathlib import Path

from backend.ai.schemas import AIObserverFeedItem

logger = logging.getLogger("ai.storage")


class AIObservationStore:
    """AI 观察项存储。实例范围：一个进程 1 个。

    线程安全：deque 的 append 是原子的，但为了配合 REST list 的快照读取，
    统一用 asyncio.Lock 串行写。
    """

    def __init__(self, *, ring_size: int = 50, jsonl_path: Path | None = None) -> None:
        self._ring: deque[AIObserverFeedItem] = deque(maxlen=max(1, ring_size))
        self._jsonl_path = jsonl_path
        self._lock = asyncio.Lock()
        if self._jsonl_path is not None:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, item: AIObserverFeedItem) -> None:
        async with self._lock:
            self._ring.append(item)
            if self._jsonl_path is not None:
                try:
                    await self._append_jsonl(item)
                except OSError as e:
                    logger.warning(
                        f"ai_observations.jsonl 写入失败: {e}",
                        extra={"tags": ["AI"], "context": {"path": str(self._jsonl_path)}},
                    )

    async def _append_jsonl(self, item: AIObserverFeedItem) -> None:
        """同步写（SSD 上 jsonl append 单行，耗时 <1ms），避免额外 aiofiles 依赖。

        虽然同步 I/O 在 asyncio 事件循环里不是最佳，但单行 jsonl append 极短，
        且所有调用路径都在 observer 后台任务里，不阻塞请求链路。
        """
        assert self._jsonl_path is not None
        line = item.model_dump_json()
        # 异步线程池里执行同步 write，保证不阻塞 loop
        await asyncio.to_thread(self._write_line_sync, line)

    def _write_line_sync(self, line: str) -> None:
        assert self._jsonl_path is not None
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    async def latest(self) -> AIObserverFeedItem | None:
        async with self._lock:
            if not self._ring:
                return None
            return self._ring[-1]

    async def list(self, *, limit: int = 20) -> list[AIObserverFeedItem]:
        async with self._lock:
            return list(self._ring)[-max(1, limit):]

    def size(self) -> int:
        return len(self._ring)

    async def load_tail_from_jsonl(self, *, limit: int = 20) -> int:
        """进程启动时从 jsonl 回灌最近 ``limit`` 条到环形缓冲。

        返回实际加载条数。JSONL 不存在 / 格式错误时返回 0（告警不抛）。
        """
        if self._jsonl_path is None or not self._jsonl_path.exists():
            return 0

        def _read_tail() -> list[str]:
            try:
                with self._jsonl_path.open("r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as e:
                logger.warning(f"读取 jsonl 失败: {e}", extra={"tags": ["AI"]})
                return []
            return [ln.strip() for ln in lines if ln.strip()]

        lines = await asyncio.to_thread(_read_tail)
        if not lines:
            return 0
        tail = lines[-limit:]
        async with self._lock:
            loaded = 0
            for ln in tail:
                try:
                    data = json.loads(ln)
                    item = AIObserverFeedItem.model_validate(data)
                    self._ring.append(item)
                    loaded += 1
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug(f"跳过损坏行: {e}", extra={"tags": ["AI"]})
                    continue
        logger.info(
            f"AI observation ring 已回灌 {loaded} 条",
            extra={"tags": ["AI"], "context": {"path": str(self._jsonl_path)}},
        )
        return loaded

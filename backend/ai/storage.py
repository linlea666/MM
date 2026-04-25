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

from backend.ai.schemas import (
    AIObserverFeedItem,
    AnalysisReport,
    AnalysisReportSummary,
)

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


class AnalysisReportStore:
    """V1.1 · 深度分析报告存储。

    与 ``AIObservationStore`` 解耦：
    - **ring 默认 20**（深度报告体积大、频次低）；
    - **JSONL 独立文件**（``analysis_reports.jsonl``）；
    - 单条体积可达 ~200KB（含三层 raw_payloads）。
    """

    def __init__(self, *, ring_size: int = 20, jsonl_path: Path | None = None) -> None:
        self._ring: deque[AnalysisReport] = deque(maxlen=max(1, ring_size))
        self._jsonl_path = jsonl_path
        self._lock = asyncio.Lock()
        if self._jsonl_path is not None:
            self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, report: AnalysisReport) -> None:
        async with self._lock:
            self._ring.append(report)
            if self._jsonl_path is not None:
                try:
                    line = report.model_dump_json()
                    await asyncio.to_thread(self._write_line_sync, line)
                except OSError as e:
                    logger.warning(
                        f"analysis_reports.jsonl 写入失败: {e}",
                        extra={"tags": ["AI"], "context": {"path": str(self._jsonl_path)}},
                    )

    def _write_line_sync(self, line: str) -> None:
        assert self._jsonl_path is not None
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    async def get(self, report_id: str) -> AnalysisReport | None:
        """先查内存 ring，没有再扫 JSONL（O(N) 全量扫；N≤数千可接受）。"""
        async with self._lock:
            for r in reversed(self._ring):
                if r.id == report_id:
                    return r
        # 内存里没找到 → 扫 jsonl
        if self._jsonl_path is None or not self._jsonl_path.exists():
            return None

        def _scan() -> AnalysisReport | None:
            try:
                with self._jsonl_path.open("r", encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        # 用 substring pre-filter 加速：只在 id 命中时才 json.loads
                        if report_id not in ln:
                            continue
                        try:
                            data = json.loads(ln)
                        except json.JSONDecodeError:
                            continue
                        if data.get("id") == report_id:
                            try:
                                return AnalysisReport.model_validate(data)
                            except ValueError:
                                return None
            except OSError as e:
                logger.warning(f"analysis_reports.jsonl 读取失败: {e}", extra={"tags": ["AI"]})
            return None

        return await asyncio.to_thread(_scan)

    async def list_summaries(self, *, limit: int = 10) -> list[AnalysisReportSummary]:
        """返回最近 N 条报告的摘要（去掉重型字段）。"""
        async with self._lock:
            tail = list(self._ring)[-max(1, limit):]
        # 新到旧，方便前端直接按时间倒序展示
        tail.reverse()
        return [
            AnalysisReportSummary(
                id=r.id,
                ts=r.ts,
                symbol=r.symbol,
                tf=r.tf,
                model_tier=r.model_tier,
                thinking_enabled=r.thinking_enabled,
                status=r.status,
                total_tokens=r.total_tokens,
                total_latency_ms=r.total_latency_ms,
                one_line=r.one_line,
            )
            for r in tail
        ]

    def size(self) -> int:
        return len(self._ring)

    async def load_tail_from_jsonl(self, *, limit: int = 20) -> int:
        """进程启动时回灌最近 ``limit`` 条到 ring。"""
        if self._jsonl_path is None or not self._jsonl_path.exists():
            return 0

        def _read_tail() -> list[str]:
            try:
                with self._jsonl_path.open("r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError as e:
                logger.warning(f"读取 analysis_reports.jsonl 失败: {e}", extra={"tags": ["AI"]})
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
                    report = AnalysisReport.model_validate(data)
                    self._ring.append(report)
                    loaded += 1
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug(f"跳过损坏行: {e}", extra={"tags": ["AI"]})
                    continue
        logger.info(
            f"AnalysisReport ring 已回灌 {loaded} 条",
            extra={"tags": ["AI"], "context": {"path": str(self._jsonl_path)}},
        )
        return loaded

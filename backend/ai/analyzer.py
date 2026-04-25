"""V1.2 · AI 综合分析编排器（OnePassAnalyzer）。

设计取舍：
- **1 次 LLM 调用**：替代老的 L1→L2→L3→L4 四层串联。
  老架构在 deepseek-v4-flash 上经常因 finish_reason="stop" 早停而 schema 验证失败；
  OnePass 把所有指标一次性喂给模型，让它"同时综合所有维度"输出一份研报，更贴合用户
  最初的"把所有指标发给 AI 让它综合分析"诉求；
- **payload = FeatureSnapshot 全量**：不再用裁剪过的 ``AIObserverInput``，
  让模型看到 23 个指标的最新值（爆仓带 / 热力图 / CHoCH / 共振 / 聪明钱…）。
  代价是单次输入 token 增加（30-50 KB JSON ≈ 10-20k input tokens），
  但 V4 模型对 1 MB 内输入完全无压力，远未触及上下文上限；
- **失败仍落盘**：模型异常时仍写一份 ``AnalysisReport(status='error')``，
  完整 raw_payloads 保留（便于排查）。

线程/并发：``analyze()`` 内部用 asyncio.Lock；外层不需要再加锁。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone

from backend.ai.agents import AgentResult, run_onepass_agent
from backend.ai.providers.base import LLMProvider
from backend.ai.schemas import (
    AIRawPayloadDump,
    AnalysisReport,
    OnePassReport,
)
from backend.ai.storage import AnalysisReportStore
from backend.rules.features import FeatureSnapshot

logger = logging.getLogger("ai.analyzer")


def _build_report_id(symbol: str, tf: str, ts_ms: int) -> str:
    """形如 ``20260425T143058Z-BTC-1h``，URL-safe + 全局唯一（精确到秒）。"""
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return f"{dt.strftime('%Y%m%dT%H%M%SZ')}-{symbol}-{tf}"


def _payload_dump(r: AgentResult) -> AIRawPayloadDump:
    return AIRawPayloadDump(
        layer=r.layer,
        model=r.model,
        tokens_total=int((r.usage or {}).get("total_tokens", 0)),
        latency_ms=r.latency_ms,
        system_prompt=r.system_prompt,
        user_prompt=r.user_prompt,
        raw_response=r.raw_response,
    )


def _onepass_to_markdown(out: OnePassReport) -> str:
    """把 OnePassReport 的结构化字段 + report_md 拼成最终展示的 markdown。

    前端 ``AnalysisReportPage`` 直接读 ``report_md``；为了让 hero / 列表 / 详情页
    多个入口拿到的内容一致，把要点 / 风险 / 重点关注三组 list 也拼接到 markdown
    顶部，再接模型自己写的 report_md。这样无论用户从哪儿点进来，都能一屏看清。
    """
    lines: list[str] = []
    bias_label = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}.get(
        out.overall_bias, out.overall_bias
    )
    lines.append(f"> **综合方向**：{bias_label}　|　**信心**：{out.confidence:.0%}")
    lines.append("")
    lines.append(f"> **一句话**：{out.one_line}")
    lines.append("")

    if out.key_takeaways:
        lines.append("## 核心要点")
        lines.append("")
        for tk in out.key_takeaways:
            lines.append(f"- {tk}")
        lines.append("")

    if out.key_risks:
        lines.append("## 关键风险")
        lines.append("")
        for r in out.key_risks:
            lines.append(f"- {r}")
        lines.append("")

    if out.next_focus:
        lines.append("## 接下来重点关注")
        lines.append("")
        for f in out.next_focus:
            lines.append(f"- {f}")
        lines.append("")

    body = (out.report_md or "").strip()
    if body:
        lines.append(body)

    return "\n".join(lines).strip()


_PRICE_RE = re.compile(r"`?([0-9]{2,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]{4,6}(?:\.[0-9]+)?)`?")


def _collect_source_prices(snapshot: dict) -> set[float]:
    """从 FeatureSnapshot dict 收集可追溯价位白名单。"""
    prices: set[float] = set()

    def add(v: object) -> None:
        if isinstance(v, (int, float)):
            fv = float(v)
            if fv > 0:
                prices.add(fv)

    # 基础
    add(snapshot.get("last_price"))
    add(snapshot.get("vwap_last"))
    add(snapshot.get("nearest_support_price"))
    add(snapshot.get("nearest_resistance_price"))

    # trailing vwap
    tv = snapshot.get("trailing_vwap_last")
    if isinstance(tv, dict):
        add(tv.get("support"))
        add(tv.get("resistance"))

    # micro poc
    mp = snapshot.get("micro_poc_last")
    if isinstance(mp, dict):
        add(mp.get("poc_price"))

    # volume profile
    vp = snapshot.get("volume_profile")
    if isinstance(vp, dict):
        add(vp.get("poc_price"))
        add(vp.get("value_area_low"))
        add(vp.get("value_area_high"))
        top_nodes = vp.get("top_nodes")
        if isinstance(top_nodes, list):
            for n in top_nodes:
                if isinstance(n, dict):
                    add(n.get("price"))

    # segment portrait
    sp = snapshot.get("segment_portrait")
    if isinstance(sp, dict):
        for k in (
            "roi_avg_price",
            "roi_limit_avg_price",
            "roi_limit_max_price",
            "pain_avg_price",
            "pain_max_price",
            "dd_trailing_current",
        ):
            add(sp.get(k))

    # list-like price carriers
    for field, keys in (
        ("hvn_nodes", ("price",)),
        ("order_blocks", ("avg_price",)),
        ("absolute_zones", ("bottom_price", "top_price")),
        ("cascade_bands", ("avg_price", "bottom_price", "top_price")),
        ("retail_stop_bands", ("avg_price", "bottom_price", "top_price")),
        ("heatmap", ("price",)),
        ("vacuums", ("low", "high")),
        ("liquidation_fuel", ("bottom", "top")),
    ):
        arr = snapshot.get(field)
        if isinstance(arr, list):
            for item in arr:
                if isinstance(item, dict):
                    for k in keys:
                        add(item.get(k))

    return prices


def _extract_report_prices(text: str, *, last_price: float | None) -> set[float]:
    """从 LLM 输出文本提取疑似价位数字。"""
    out: set[float] = set()
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        # 过滤明显非价位数字（时间戳/年份/小整数等）
        if v < 1000:
            continue
        if last_price and last_price > 0:
            # 保留合理价格域，避免把时间戳误识别成价位
            if not (last_price * 0.35 <= v <= last_price * 3.5):
                continue
        out.add(v)
    return out


def _is_price_traced(v: float, candidates: set[float]) -> bool:
    """是否可在来源白名单中匹配（允许四舍五入/轻微偏差）。"""
    for c in candidates:
        # 允许 0.35% 或 30 美元（取大），兼容格式化与轻微四舍五入
        tol = max(30.0, c * 0.0035)
        if abs(v - c) <= tol:
            return True
    return False


def _audit_report_price_sources(
    out: OnePassReport, *, snapshot_json: str
) -> tuple[OnePassReport, int, list[float]]:
    """审计报告价位来源；返回（out, 未追溯数量, 未追溯样本价位）。"""
    try:
        snap = json.loads(snapshot_json)
    except Exception:  # noqa: BLE001
        return out, 0, []
    if not isinstance(snap, dict):
        return out, 0, []

    last_price = snap.get("last_price")
    last_price_num = float(last_price) if isinstance(last_price, (int, float)) else None
    source_prices = _collect_source_prices(snap)
    if not source_prices:
        return out, 0, []

    text_pool = "\n".join(
        [out.one_line, *out.key_takeaways, *out.key_risks, *out.next_focus, out.report_md]
    )
    used_prices = _extract_report_prices(text_pool, last_price=last_price_num)
    if not used_prices:
        return out, 0, []

    unknown = sorted(p for p in used_prices if not _is_price_traced(p, source_prices))
    if not unknown:
        return out, 0, []

    # 置信度下调：每个未知价位 -0.02，最多 -0.15
    penalty = min(0.15, 0.02 * len(unknown))
    out.confidence = max(0.0, out.confidence - penalty)

    unknown_str = ", ".join(f"`{p:,.0f}`" for p in unknown[:8])
    tail = ""
    if len(unknown) > 8:
        tail = f" 等 {len(unknown)} 个价位"
    audit_note = (
        "\n\n## 价位来源审计\n"
        f"- ⚠️ 检测到不可追溯价位：{unknown_str}{tail}。\n"
        "- 已按规则自动降级 confidence，并建议仅使用可在 input 追溯的价位执行。"
    )
    out.report_md = (out.report_md or "").rstrip() + audit_note
    return out, len(unknown), unknown[:8]


class OnePassAnalyzer:
    """单次综合分析编排器 + AnalysisReport 持久化。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        report_store: AnalysisReportStore,
        model_tier: str = "flash",
        thinking_enabled: bool = False,
        max_tokens: int = 8192,
        timeout_s: float = 120.0,
        temperature: float = 0.25,
    ) -> None:
        self._provider = provider
        self._store = report_store
        self._tier = model_tier
        self._thinking = thinking_enabled
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._temperature = temperature
        self._lock = asyncio.Lock()

    async def analyze(self, snap: FeatureSnapshot) -> AnalysisReport:
        """主入口：跑一次 OnePass 并落盘一条 AnalysisReport。"""
        async with self._lock:  # 同 analyzer 串行，避免并发烧 token
            return await self._analyze_unsafe(snap)

    async def _analyze_unsafe(self, snap: FeatureSnapshot) -> AnalysisReport:
        ts_ms = int(time.time() * 1000)
        report_id = _build_report_id(snap.symbol, snap.tf, ts_ms)
        # 完整 FeatureSnapshot 投影（不裁剪），让模型看到所有指标
        snap_json = snap.model_dump_json()

        started = time.perf_counter()

        result = await run_onepass_agent(
            provider=self._provider,
            payload_json=snap_json,
            model_tier=self._tier,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout_s=self._timeout_s,
            thinking_enabled=self._thinking,
        )

        total_latency_ms = int((time.perf_counter() - started) * 1000)
        total_tokens = int((result.usage or {}).get("total_tokens", 0))

        out: OnePassReport | None = result.output  # type: ignore[assignment]
        if out is None:
            status: str = "error"
            error_reason = result.error or "onepass 调用失败"
            one_line = ""
            report_md = ""
            unknown_price_count = 0
            unknown_price_samples: list[float] = []
        else:
            out, unknown_price_count, unknown_price_samples = _audit_report_price_sources(
                out, snapshot_json=snap_json
            )
            status = "ok"
            error_reason = None
            one_line = out.one_line
            report_md = _onepass_to_markdown(out)
            if unknown_price_count > 0:
                logger.warning(
                    "OnePass report 出现不可追溯价位",
                    extra={
                        "tags": ["AI", "DATA_AUDIT"],
                        "context": {
                            "symbol": snap.symbol,
                            "tf": snap.tf,
                            "report_id": report_id,
                            "unknown_price_count": unknown_price_count,
                        },
                    },
                )

        report = AnalysisReport(
            id=report_id,
            ts=ts_ms,
            symbol=snap.symbol,
            tf=snap.tf,
            model_tier=self._tier,  # type: ignore[arg-type]
            thinking_enabled=self._thinking,
            status=status,  # type: ignore[arg-type]
            error_reason=error_reason,
            total_tokens=total_tokens,
            total_latency_ms=total_latency_ms,
            unknown_price_count=unknown_price_count,
            unknown_price_samples=unknown_price_samples,
            one_line=one_line,
            report_md=report_md,
            raw_payloads=[_payload_dump(result)],
            data_slice=snap_json,
        )

        await self._store.append(report)
        logger.info(
            f"AI onepass analyze {snap.symbol}/{snap.tf} status={status} "
            f"latency={total_latency_ms}ms tokens={total_tokens} id={report_id}",
            extra={"tags": ["AI"], "context": {"error": result.error}},
        )
        return report


# Backwards-compat alias：service.py / 测试代码以前 import DeepAnalyzer，
# 名字保留以减少 churn；行为完全等价于 OnePassAnalyzer。
DeepAnalyzer = OnePassAnalyzer

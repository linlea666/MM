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

# `78,759`（trailing_vwap_last.resistance）/ 78,759 (source=...) / 78,759（cascade_bands long_fuel）
_PRICED_SOURCE_RE = re.compile(
    r"`?([0-9]{2,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]{4,6}(?:\.[0-9]+)?)`?"
    r"\s*[（(]\s*"
    r"(?:source\s*[:=]\s*)?"
    r"([^（）()\n]{2,80}?)"
    r"\s*[）)]"
)
_TOKEN_SPLIT_RE = re.compile(r"[._]+")


def _collect_source_prices_by_field(snapshot: dict) -> dict[str, set[float]]:
    """按字段路径分桶收集价位（用于 (price, source) 双绑定审计）。

    键名是规范化的 dot.path（不含 ``[]`` 下标），同时为每个字段维护一个粗粒度桶
    （如 ``cascade_bands`` 包含所有 ``avg/top/bottom_price`` × ``side``），
    以便 AI 用简短标注（``cascade_bands``）也能命中。
    """
    buckets: dict[str, set[float]] = {}

    def add(key: str, v: object) -> None:
        if isinstance(v, (int, float)):
            fv = float(v)
            if fv > 0:
                buckets.setdefault(key, set()).add(fv)

    add("last_price", snapshot.get("last_price"))
    add("vwap_last", snapshot.get("vwap_last"))
    add("nearest_support_price", snapshot.get("nearest_support_price"))
    add("nearest_resistance_price", snapshot.get("nearest_resistance_price"))

    nested_objects: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("trailing_vwap_last", ("support", "resistance")),
        ("micro_poc_last", ("poc_price",)),
        ("smart_money_ongoing", ("avg_price",)),
        ("trend_purity_last", ("avg_price",)),
    )
    for parent, sub_keys in nested_objects:
        node = snapshot.get(parent)
        if not isinstance(node, dict):
            continue
        for sk in sub_keys:
            v = node.get(sk)
            add(f"{parent}.{sk}", v)
            add(parent, v)

    vp = snapshot.get("volume_profile")
    if isinstance(vp, dict):
        for k in ("poc_price", "value_area_low", "value_area_high"):
            v = vp.get(k)
            add(f"volume_profile.{k}", v)
            add("volume_profile", v)
        for n in vp.get("top_nodes") or []:
            if isinstance(n, dict):
                v = n.get("price")
                add("volume_profile.top_nodes", v)
                add("volume_profile", v)

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
            v = sp.get(k)
            add(f"segment_portrait.{k}", v)
            add("segment_portrait", v)

    list_fields: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("hvn_nodes", ("price",)),
        ("order_blocks", ("avg_price",)),
        ("absolute_zones", ("bottom_price", "top_price")),
        ("cascade_bands", ("avg_price", "bottom_price", "top_price")),
        ("retail_stop_bands", ("avg_price", "bottom_price", "top_price")),
        ("heatmap", ("price",)),
        ("vacuums", ("low", "high")),
        ("liquidation_fuel", ("bottom", "top")),
    )
    for field, keys in list_fields:
        arr = snapshot.get(field)
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            raw_side = item.get("side")
            side = raw_side.lower() if isinstance(raw_side, str) and raw_side else None
            for k in keys:
                v = item.get(k)
                add(field, v)
                add(f"{field}.{k}", v)
                if side:
                    add(f"{field}.{side}", v)
                    add(f"{field}.{side}.{k}", v)

    return buckets


def _collect_source_prices(snapshot: dict) -> set[float]:
    """全局可追溯价位白名单（保留旧接口；由 by_field 桶 union 得到）。"""
    prices: set[float] = set()
    for s in _collect_source_prices_by_field(snapshot).values():
        prices.update(s)
    return prices


def _normalize_source_token(s: str) -> str:
    """规范化 AI 写的来源标注，便于对齐 buckets 的 key。"""
    s = s.strip().strip("`*\"' ")
    s = re.sub(r"[（(]", ".", s)
    s = re.sub(r"[）)]", "", s)
    s = re.sub(r"[·:：\-→/，,;；\s]+", ".", s)
    s = re.sub(r"\.+", ".", s)
    return s.strip(".").lower()


def _resolve_source_prices(
    buckets: dict[str, set[float]], source: str
) -> set[float] | None:
    """根据来源标注解析其对应的字段价位集合；解析失败返回 ``None``（保守跳过）。"""
    if not source:
        return None
    norm = _normalize_source_token(source)
    if not norm:
        return None

    if norm in buckets:
        return buckets[norm]

    matches = [k for k in buckets if k.startswith(norm) or norm.startswith(k)]
    if matches:
        matches.sort(key=len, reverse=True)
        return buckets[matches[0]]

    tokens = [t for t in _TOKEN_SPLIT_RE.split(norm) if t]
    if not tokens:
        return None
    pooled: set[float] = set()
    matched = 0
    for k, vs in buckets.items():
        kt = _TOKEN_SPLIT_RE.split(k)
        if any(t in kt for t in tokens):
            pooled.update(vs)
            matched += 1
    return pooled if matched > 0 else None


def _extract_report_prices(text: str, *, last_price: float | None) -> set[float]:
    """从 LLM 输出文本提取疑似价位数字。"""
    out: set[float] = set()
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        if v < 1000:
            continue
        if last_price and last_price > 0:
            if not (last_price * 0.35 <= v <= last_price * 3.5):
                continue
        out.add(v)
    return out


def _extract_priced_sources(
    text: str, *, last_price: float | None
) -> list[tuple[float, str]]:
    """提取 (价位, 来源标注) 对，用于双绑定校验。

    仅取来源**含字母**的条目，避免把 ``(下方 +1.2%)`` 这种纯比例标注误判成 source。
    """
    out: list[tuple[float, str]] = []
    for m in _PRICED_SOURCE_RE.finditer(text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if v < 1000:
            continue
        if last_price and last_price > 0:
            if not (last_price * 0.35 <= v <= last_price * 3.5):
                continue
        src = (m.group(2) or "").strip()
        if not src or not re.search(r"[A-Za-z_]", src):
            continue
        out.append((v, src))
    return out


def _is_round_thousand(v: float) -> bool:
    """末三位为 0 → 典型「整千估算价」，需要更严苛的容差。"""
    if v < 1000:
        return False
    return abs(v - round(v / 1000) * 1000) < 0.5


def _is_price_traced(v: float, candidates: set[float]) -> bool:
    """是否可在来源价位集合中匹配。

    - 普通价位：容差 ``max(10, c * 0.001)``（0.1% 或 10 美元，兼容四舍五入与字符串格式化）；
    - 整千估算（末三位 000）：收紧到 ``max(5, c * 0.0005)``，
      防止 ``78,000`` 借邻近 ``77,850`` 蒙混过关。
    """
    is_round = _is_round_thousand(v)
    for c in candidates:
        if is_round:
            tol = max(5.0, c * 0.0005)
        else:
            tol = max(10.0, c * 0.001)
        if abs(v - c) <= tol:
            return True
    return False


def _audit_report_price_sources(
    out: OnePassReport, *, snapshot_json: str
) -> tuple[OnePassReport, int, list[float]]:
    """审计报告价位来源；返回 ``(out, 未追溯数量, 未追溯样本价位)``。

    审计两层：
      1. **(price, source) 双绑定**：报告里以 ``价位（field.path）`` 形式标注的，
         必须能在 ``field.path`` 对应的字段桶里找到该价位；找不到即视为来源伪造。
      2. **全局白名单兜底**：未带来源标注的价位，落到全字段 union 白名单里检查。
    """
    try:
        snap = json.loads(snapshot_json)
    except Exception:  # noqa: BLE001
        return out, 0, []
    if not isinstance(snap, dict):
        return out, 0, []

    last_price = snap.get("last_price")
    last_price_num = (
        float(last_price) if isinstance(last_price, (int, float)) else None
    )

    buckets = _collect_source_prices_by_field(snap)
    if not buckets:
        return out, 0, []
    all_prices: set[float] = set()
    for s in buckets.values():
        all_prices.update(s)

    text_pool = "\n".join(
        [out.one_line, *out.key_takeaways, *out.key_risks, *out.next_focus, out.report_md]
    )
    priced_sources = _extract_priced_sources(text_pool, last_price=last_price_num)
    used_prices = _extract_report_prices(text_pool, last_price=last_price_num)

    audited_pairs: set[float] = set()
    unknown: list[float] = []

    for v, src in priced_sources:
        audited_pairs.add(v)
        cand = _resolve_source_prices(buckets, src)
        if cand is None:
            if not _is_price_traced(v, all_prices):
                unknown.append(v)
            continue
        if not _is_price_traced(v, cand):
            unknown.append(v)

    for v in used_prices:
        if v in audited_pairs:
            continue
        if not _is_price_traced(v, all_prices):
            unknown.append(v)

    seen: set[float] = set()
    unknown_dedup: list[float] = []
    for p in sorted(unknown):
        if p in seen:
            continue
        seen.add(p)
        unknown_dedup.append(p)

    if not unknown_dedup:
        return out, 0, []

    penalty = min(0.15, 0.02 * len(unknown_dedup))
    out.confidence = max(0.0, out.confidence - penalty)

    unknown_str = ", ".join(f"`{p:,.0f}`" for p in unknown_dedup[:8])
    tail = ""
    if len(unknown_dedup) > 8:
        tail = f" 等 {len(unknown_dedup)} 个价位"
    audit_note = (
        "\n\n## 价位来源审计\n"
        f"- ⚠️ 检测到不可追溯价位：{unknown_str}{tail}。\n"
        "- 已按规则自动降级 confidence，并建议仅使用可在 input 追溯的价位执行。"
    )
    out.report_md = (out.report_md or "").rstrip() + audit_note
    return out, len(unknown_dedup), unknown_dedup[:8]


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

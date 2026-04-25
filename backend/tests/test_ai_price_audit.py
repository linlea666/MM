from backend.ai.analyzer import (
    _audit_report_price_sources,
    _collect_source_prices_by_field,
    _is_price_traced,
    _resolve_source_prices,
    _strip_no_trade_specifics,
)
from backend.ai.schemas import OnePassReport


def _base_report() -> OnePassReport:
    return OnePassReport(
        one_line="偏空震荡，先观望。",
        overall_bias="bearish",
        confidence=0.5,
        key_takeaways=["动态支撑 `77,466`，阻力 `78,760`。"],
        key_risks=[],
        next_focus=[],
        report_md=(
            "## 趋势画像\n"
            "价格关注 `77,466` 与 `78,760`，并结合 CVD 单边性、时间热力图与主力段状态判断是否观望。"
            "当前为示例测试文本，仅用于满足 OnePassReport 最小长度约束。"
        ),
    )


def test_price_audit_no_unknown_prices() -> None:
    out = _base_report()
    snap_json = (
        '{"last_price":77490.09,'
        '"trailing_vwap_last":{"support":77465.94820500101,"resistance":78759.61433944982},'
        '"cascade_bands":[{"top_price":79297.0,"bottom_price":79000.0,"avg_price":79150.0}]}'
    )
    audited, cnt, samples = _audit_report_price_sources(out, snapshot_json=snap_json)
    assert cnt == 0
    assert samples == []
    assert abs(audited.confidence - 0.5) < 1e-9
    assert "价位来源审计" not in audited.report_md


def test_price_audit_flags_unknown_price_and_penalty() -> None:
    out = _base_report()
    out.report_md += "\n额外关注 `76,066`。"
    snap_json = (
        '{"last_price":77490.09,'
        '"trailing_vwap_last":{"support":77465.94820500101,"resistance":78759.61433944982},'
        '"retail_stop_bands":[{"top_price":66287.19,"bottom_price":65818.69,"avg_price":66052.94}]}'
    )
    audited, cnt, samples = _audit_report_price_sources(out, snapshot_json=snap_json)
    assert cnt >= 1
    assert len(samples) >= 1
    assert audited.confidence < 0.5
    assert "价位来源审计" in audited.report_md


def test_price_audit_catches_round_thousand_estimate() -> None:
    """末三位 000 的整千估算价应被严格容差抓出（旧 0.35% 容差会漏）。"""
    out = _base_report()
    out.report_md += "\n激进止损落在 `78,000`。"
    snap_json = (
        '{"last_price":77490.09,'
        '"trailing_vwap_last":{"support":77465.94820500101,"resistance":78759.61433944982},'
        '"absolute_zones":[{"bottom_price":77600.0,"top_price":77850.7}]}'
    )
    audited, cnt, samples = _audit_report_price_sources(out, snapshot_json=snap_json)
    assert cnt >= 1
    assert 78000.0 in samples
    assert audited.confidence < 0.5


def test_price_audit_catches_mismatched_source() -> None:
    """价位真实来自 liquidation_fuel，AI 标成 cascade_bands → 双绑定应抓出。"""
    out = _base_report()
    out.report_md += "\n关键磁吸位 `80,044`（cascade_bands.long_fuel）。"
    snap_json = (
        '{"last_price":77490.09,'
        '"trailing_vwap_last":{"support":77465.94820500101,"resistance":78759.61433944982},'
        '"cascade_bands":[{"side":"short_fuel","top_price":76300.0,"bottom_price":76050.0,"avg_price":76175.0}],'
        '"liquidation_fuel":[{"side":"long","top":80100.0,"bottom":80044.0}]}'
    )
    audited, cnt, samples = _audit_report_price_sources(out, snapshot_json=snap_json)
    assert cnt >= 1
    assert 80044.0 in samples
    assert audited.confidence < 0.5
    assert "价位来源审计" in audited.report_md


def test_price_audit_passes_when_source_matches() -> None:
    """价位与来源标注真实匹配时，双绑定不应误伤。"""
    out = _base_report()
    out.report_md += "\n下方第一支撑 `77,466`（trailing_vwap_last.support）。"
    snap_json = (
        '{"last_price":77490.09,'
        '"trailing_vwap_last":{"support":77465.94820500101,"resistance":78759.61433944982}}'
    )
    audited, cnt, _samples = _audit_report_price_sources(out, snapshot_json=snap_json)
    assert cnt == 0
    assert abs(audited.confidence - 0.5) < 1e-9


def test_collect_buckets_subkey_paths() -> None:
    """分桶器应同时建立 dot.path 子键桶和父级粗桶。"""
    snap = {
        "last_price": 77490.09,
        "trailing_vwap_last": {"support": 77465.95, "resistance": 78759.61},
        "cascade_bands": [
            {"side": "long_fuel", "top_price": 79300.0, "bottom_price": 79000.0, "avg_price": 79150.0}
        ],
    }
    buckets = _collect_source_prices_by_field(snap)
    assert "trailing_vwap_last.support" in buckets
    assert 77465.95 in buckets["trailing_vwap_last.support"]
    assert "trailing_vwap_last" in buckets
    assert {77465.95, 78759.61}.issubset(buckets["trailing_vwap_last"])
    assert "cascade_bands.long_fuel" in buckets
    assert {79000.0, 79150.0, 79300.0}.issubset(buckets["cascade_bands.long_fuel"])
    assert "cascade_bands" in buckets


def test_resolve_source_handles_aliases() -> None:
    snap = {
        "last_price": 77490.09,
        "trailing_vwap_last": {"support": 77465.95, "resistance": 78759.61},
    }
    buckets = _collect_source_prices_by_field(snap)
    direct = _resolve_source_prices(buckets, "trailing_vwap_last.support")
    assert direct is not None and 77465.95 in direct
    parent = _resolve_source_prices(buckets, "trailing_vwap_last")
    assert parent is not None and 78759.61 in parent
    fuzzy = _resolve_source_prices(buckets, "trailing_vwap last support")
    assert fuzzy is not None and 77465.95 in fuzzy
    assert _resolve_source_prices(buckets, "totally_unknown_field") is None


def test_is_price_traced_tolerance_tightened() -> None:
    """0.1% 容差：78,760 仍能匹配 78,759.61；77,800 不能贴 77,466。"""
    cands = {77465.95, 78759.61}
    assert _is_price_traced(78760.0, cands) is True
    assert _is_price_traced(77466.0, cands) is True
    # 旧 0.35% 容差（≈271 美元）会通过；新 0.1% 容差（≈77 美元）应拒绝
    assert _is_price_traced(77800.0, cands) is False


def test_is_price_traced_round_thousand_strict() -> None:
    """末三位 000 的整千数被收紧到 0.05% / 5 美元；不应贴邻近非整数。"""
    cands = {77850.7}
    assert _is_price_traced(78000.0, cands) is False
    assert _is_price_traced(77850.0, cands) is True


def test_price_audit_does_not_match_timestamp_substring() -> None:
    """13 位时间戳 ``1777014000000`` 子串 ``177701`` 不应被审计误识别成价位。

    线上回归：Prompt v3.1 的报告里写 "start_time 1777014000000"，
    旧正则贪婪吃了 6 位整数 ``177701``，再被 ``last_price × [0.35, 3.5]``
    价格域过滤通过 → 误报「不可追溯价位 177,701」。
    """
    out = _base_report()
    out.report_md += (
        "\n当前吸筹段（start_time 1777014000000）均价 `77,425`，"
        "中位止盈 `81,069`，极限痛点 `74,328`。"
        "\n时间预算：22 根 K 线（约 22h），极限 81 根（约 81h）。"
    )
    snap_json = (
        '{"last_price":77624.0,'
        '"trailing_vwap_last":{"support":77465.95,"resistance":78759.61},'
        '"smart_money_ongoing":{"avg_price":77424.81666666667},'
        '"segment_portrait":{"roi_avg_price":77424.82,"roi_limit_avg_price":81068.87,'
        '"roi_limit_max_price":84197.50,"pain_avg_price":75873.81,'
        '"pain_max_price":74328.15}}'
    )
    audited, cnt, samples = _audit_report_price_sources(out, snapshot_json=snap_json)
    assert 177701.0 not in samples, f"时间戳子串误报: samples={samples}"
    # 23 ≈ 22 / 81 这种小整数（< 1000）不在 _PRICE_RE 字符域内，也不应误命中
    assert all(p >= 1000 for p in samples)
    assert cnt == 0


def test_strip_no_trade_specifics_drops_scenario_prices() -> None:
    """primary_action=no_trade 时，「风险与场景 / 操作矩阵」里的执行级具体价应被剥离。"""
    out = OnePassReport(
        one_line="数据缺失，建议观望。",
        overall_bias="neutral",
        confidence=0.31,
        key_takeaways=["关键原子表全 0，confidence 已降。"],
        key_risks=[],
        next_focus=[],
        report_md=(
            "## 风险与场景\n"
            "- 若价格跌破 `77,466`（trailing_vwap.support）：可考虑轻仓短空，"
            "止损 `78,000`。\n"
            "- 若价格突破 `78,760`：转为偏多，目标 `79,297`，止损 `77,400`。\n\n"
            "## 操作矩阵\n"
            "- 做多：entry_zone `78,800` / 止损 `77,400` / TP1 `80,000`\n\n"
            "## 决策摘要\n"
            "- primary_action: no_trade\n"
            "- switch_trigger: 若价格跌破 `77,466` 且 CVD 收敛比 < 0.3，则切换为 short。\n"
        ),
    )
    audited, scrubbed = _strip_no_trade_specifics(out)
    assert scrubbed, "no_trade 应触发剥离"
    md = audited.report_md
    # 场景章节里的执行级具体价已被替换
    assert "止损 `78,000`" not in md
    assert "止损 `77,400`" not in md
    assert "TP1 `80,000`" not in md
    assert "<待场景成立后再定>" in md
    # 决策摘要中的 switch_trigger 条件价**保留**（这是反手必备的硬条件）
    assert "switch_trigger" in md
    assert "`77,466`" in md  # 该价位在多个章节都出现，至少在决策摘要保留
    # 末尾追加护栏说明
    assert "## 不交易护栏" in md


def test_strip_no_trade_specifics_noop_when_action_is_long_or_short() -> None:
    """非 no_trade 时不应做任何剥离。"""
    out = OnePassReport(
        one_line="偏多入场。",
        overall_bias="bullish",
        confidence=0.6,
        key_takeaways=["趋势强，主力吸筹延续。"],
        key_risks=[],
        next_focus=[],
        report_md=(
            "## 风险与场景\n"
            "- 突破 `78,760` 后做多，止损 `77,400`，目标 `79,297`。\n\n"
            "## 决策摘要\n"
            "- primary_action: long\n"
            "- switch_trigger: 跌破 `77,466` 切换 short。\n"
        ),
    )
    audited, scrubbed = _strip_no_trade_specifics(out)
    assert not scrubbed
    assert "止损 `77,400`" in audited.report_md
    assert "<待场景成立后再定>" not in audited.report_md
    assert "## 不交易护栏" not in audited.report_md

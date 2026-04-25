from backend.ai.analyzer import _audit_report_price_sources
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

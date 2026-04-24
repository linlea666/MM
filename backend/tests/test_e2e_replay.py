"""端到端回放测试：把真实 HFD + Binance 快照灌进完整管道验证一致性。

**前置**：需要先跑一次抓取脚本生成 fixture（只本地跑）::

    python scripts/capture_hfd_snapshot.py --symbol BTC --tf 30m

若仓库内没有任何 ``backend/tests/fixtures/upstream/*`` 快照目录，本文件整体 skip，
CI 不会因为缺 fixture 而挂。

覆盖矩阵：
    L1 行级同构
        - test_parsers_accept_all_fixture_payloads
            22 个原始 JSON 全部能被 parser 成功消费（不抛异常、有模型产出）
        - test_engine_collect_once_populates_atoms_tables
            FixtureHFDClient + FixtureExchangeClient + 真 engine → 写库后每张"被 schedule"
            的 atoms 表的行数满足口径

    L2 派生/黄金
        - test_feature_snapshot_has_core_fields
            FeatureExtractor 能产出非空 snapshot，关键派生字段已填充
        - test_rule_runner_builds_dashboard
            RuleRunner 完整跑完，DashboardSnapshot 每个模块都产出
        - test_golden_latest_absolute_zone_reaches_snapshot
            fixture 里"最新的"absolute_zone 必然进 snap.absolute_zones
        - test_golden_strongest_heatmap_reaches_snapshot
            fixture 里 intensity 最高的 heatmap 行必然进 snap.heatmap
        - test_golden_resonance_counts_match_db
            fixture 里的 resonance 行在 DB 能一一对应（去重后）
        - test_golden_smart_money_ongoing_matches_fixture
            fixture 的 Ongoing 趋势成本段必然出现在 snap.smart_money_ongoing
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.collector.engine import CollectorEngine
from backend.collector.hfd_client import HFD_INDICATORS
from backend.collector.parsers import parse_all
from backend.rules.features import FeatureExtractor
from backend.rules.runner import RuleRunner
from backend.storage.repositories import AtomRepositories, KlineRepository
from backend.tests.fixtures.replay_mocks import (
    FixtureExchangeClient,
    FixtureHFDClient,
    discover_snapshots,
    load_snapshot_meta,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "upstream"


def _snapshot_params() -> list[pytest.param]:
    snaps = discover_snapshots(FIXTURE_ROOT)
    return [pytest.param(p, id=p.name) for p in snaps]


_PARAMS = _snapshot_params()
_SKIP_REASON = (
    "没有 fixture 快照；运行 `python scripts/capture_hfd_snapshot.py --symbol BTC --tf 30m` "
    "生成后再跑 E2E 回放测试。"
)


pytestmark = pytest.mark.skipif(len(_PARAMS) == 0, reason=_SKIP_REASON)


# ─── 共享辅助：把 fixture 灌进 engine ───


async def _run_collect_once(snap_dir: Path, db, settings) -> tuple[str, str, dict]:
    meta = load_snapshot_meta(snap_dir)
    symbol = meta["symbol"]
    tf = meta["tf"]
    kline_repo = KlineRepository(db)
    atoms = AtomRepositories(db)
    hfd = FixtureHFDClient(snap_dir)
    exchange = FixtureExchangeClient(snap_dir)
    engine = CollectorEngine(
        settings=settings, hfd=hfd, exchange=exchange,
        kline_repo=kline_repo, atoms=atoms,
    )
    await engine.collect_once(symbol, tfs=[tf])
    return symbol, tf, meta


def _read_fixture(snap_dir: Path, name: str) -> dict:
    path = snap_dir / name
    if not path.exists():
        pytest.skip(f"fixture {name} 不存在于 {snap_dir.name}")
    return json.loads(path.read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════════
# L1 · 行级同构
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("snap_dir", _PARAMS)
def test_parsers_accept_all_fixture_payloads(snap_dir: Path):
    """22 个 HFD 端点的 fixture 都能被 parser 吃下，无异常、多数产出 model。"""
    meta = load_snapshot_meta(snap_dir)
    symbol = meta["symbol"]
    tf = meta["tf"]
    parser_errors: list[str] = []
    empty_parsers: list[str] = []

    indicators_with_fixture: list[str] = []
    for ind in HFD_INDICATORS:
        path = snap_dir / f"{ind}.json"
        if not path.exists():
            continue
        indicators_with_fixture.append(ind)
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            result = parse_all(symbol=symbol, tf=tf, indicator=ind, payload=payload)
        except Exception as e:  # noqa: BLE001
            parser_errors.append(f"{ind}: {e!r}")
            continue
        if result.total() == 0:
            empty_parsers.append(ind)

    assert not parser_errors, f"parser 异常: {parser_errors}"
    # 允许少量端点 fixture 确实空（如 liq_vacuum 在平静市场可能真为 0 条）
    assert (
        len(indicators_with_fixture) - len(empty_parsers)
        >= int(len(indicators_with_fixture) * 0.75)
    ), f"过多 parser 返回空: {empty_parsers}"


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_engine_collect_once_populates_atoms_tables(
    snap_dir: Path, db, settings, configured_logging
):
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)

    n_kline = await db.fetch_scalar(
        "SELECT COUNT(1) FROM atoms_klines WHERE symbol=? AND tf=?", (symbol, tf)
    )
    assert n_kline > 0, "K 线未入库"

    key_tables = [
        "atoms_cvd",
        "atoms_vwap",
        "atoms_imbalance",
        "atoms_poc_shift",
        "atoms_micro_poc",
        "atoms_trailing_vwap",
        "atoms_power_imbalance",
        "atoms_trend_exhaustion",
        "atoms_smart_money",
        "atoms_order_blocks",
        "atoms_absolute_zones",
        "atoms_trend_purity",
        "atoms_resonance_events",
        "atoms_sweep_events",
        "atoms_heatmap",
        "atoms_hvn_nodes",
        "atoms_time_heatmap",
        "atoms_trend_saturation",
    ]
    empty_tables: list[str] = []
    for t in key_tables:
        n = await db.fetch_scalar(
            f"SELECT COUNT(1) FROM {t} WHERE symbol=? AND tf=?", (symbol, tf)
        )
        if not n:
            empty_tables.append(t)
    # 允许 <=2 张表真实空（sweep/saturation 在极平静时可能无事件）
    assert len(empty_tables) <= 2, f"过多关键 atoms 表为空: {empty_tables}"


# ════════════════════════════════════════════════════════════════════
# L2 · 派生 & 黄金
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_feature_snapshot_has_core_fields(
    snap_dir: Path, db, settings, configured_logging
):
    symbol, tf, meta = await _run_collect_once(snap_dir, db, settings)
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract(symbol, tf)
    assert snap is not None
    assert snap.symbol == symbol and snap.tf == tf
    assert snap.last_price > 0
    if meta.get("anchor_ts"):
        assert snap.anchor_ts == meta["anchor_ts"]

    present: list[str] = []
    if snap.vwap_last is not None:
        present.append("vwap_last")
    if snap.cvd_slope is not None:
        present.append("cvd_slope")
    if snap.atr is not None and snap.atr > 0:
        present.append("atr")
    if snap.hvn_nodes:
        present.append("hvn_nodes")
    if snap.absolute_zones:
        present.append("absolute_zones")
    if snap.heatmap:
        present.append("heatmap")
    assert len(present) >= 4, f"关键派生字段缺失太多，仅有: {present}"


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_rule_runner_builds_dashboard(
    snap_dir: Path, db, settings, configured_logging
):
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    runner = RuleRunner(db, config=settings.rules_defaults)
    dash = await runner.run(symbol, tf)

    assert dash.symbol == symbol and dash.tf == tf
    assert dash.current_price > 0
    assert dash.hero.action_conclusion
    assert 0 <= dash.hero.stars <= 5
    assert dash.behavior.main
    assert dash.phase.current
    assert dash.participation.level
    assert len(dash.capability_scores) == 4
    assert len(dash.plans) >= 1

    payload = dash.model_dump(mode="json")
    assert "hero" in payload


# ─── Golden 断言 ───


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_latest_absolute_zone_reaches_snapshot(
    snap_dir: Path, db, settings, configured_logging
):
    """fixture 里最新 absolute_zone（start_time 最大）必然进 snap.absolute_zones。

    对应官方图上最新出现的那个红/绿箭头——DB 一定能找到 1:1 的行。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _read_fixture(snap_dir, "absolute_zones.json")
    rows = [r for r in (raw.get("order_blocks") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture absolute_zones 为空")

    latest = max(rows, key=lambda r: int(r.get("start_time", 0)))

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract(symbol, tf)
    assert snap is not None
    found = any(
        abs(z.bottom_price - float(latest["bottom_price"])) < 1e-4
        and abs(z.top_price - float(latest["top_price"])) < 1e-4
        and z.type == str(latest["type"])
        for z in snap.absolute_zones
    )
    assert found, (
        f"最新 absolute_zone (start={latest.get('start_time')}, "
        f"type={latest.get('type')}, "
        f"{latest.get('bottom_price')}-{latest.get('top_price')}) 未进 snapshot"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_strongest_heatmap_reaches_snapshot(
    snap_dir: Path, db, settings, configured_logging
):
    """fixture 里 intensity 最大的 heatmap 行必然进 snap.heatmap。

    对应图上最粗的那道清算磁吸带。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _read_fixture(snap_dir, "liq_heatmap.json")
    rows = [r for r in (raw.get("heatmap_data") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture liq_heatmap 为空")

    strongest = max(rows, key=lambda r: float(r.get("intensity") or 0))

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract(symbol, tf)
    assert snap is not None
    found = any(
        abs(b.price - float(strongest["price"])) < 1e-4
        and b.type == str(strongest["type"])
        and abs(b.intensity - float(strongest["intensity"])) < 1e-6
        for b in snap.heatmap
    )
    assert found, (
        f"最强 heatmap band (price={strongest.get('price')}, "
        f"intensity={strongest.get('intensity')}, type={strongest.get('type')}) 未进 snapshot"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_resonance_counts_match_db(
    snap_dir: Path, db, settings, configured_logging
):
    """fixture 里每条 cross_exchange_resonance 在 DB 去重后行数严格相等。"""
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _read_fixture(snap_dir, "cross_exchange_resonance.json")
    rows = [r for r in (raw.get("cross_exchange_resonance") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture resonance 为空")

    uniq = {
        (int(r["timestamp"]), float(r["price"]), str(r["direction"]))
        for r in rows
    }
    n_db = await db.fetch_scalar(
        "SELECT COUNT(1) FROM atoms_resonance_events WHERE symbol=? AND tf=?",
        (symbol, tf),
    )
    assert n_db == len(uniq), (
        f"resonance 入库行数与 fixture 去重后不一致: db={n_db} fixture_uniq={len(uniq)}"
    )

    top = max(rows, key=lambda r: int(r.get("count") or 0))
    row = await db.fetchone(
        "SELECT count FROM atoms_resonance_events "
        "WHERE symbol=? AND tf=? AND ts=? AND price=? AND direction=?",
        (symbol, tf, int(top["timestamp"]), float(top["price"]), str(top["direction"])),
    )
    assert row is not None, (
        f"fixture 最大 resonance 未入库: ts={top['timestamp']} "
        f"price={top['price']} dir={top['direction']}"
    )
    assert int(row["count"]) == int(top["count"])


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_smart_money_ongoing_matches_fixture(
    snap_dir: Path, db, settings, configured_logging
):
    """fixture 内 Ongoing 趋势成本段必然映射到 snap.smart_money_ongoing。

    对应官方图上最核心的"主力持仓成本带"——必须 1:1 一致。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _read_fixture(snap_dir, "smart_money_cost.json")
    rows = [r for r in (raw.get("smart_money_cost") or []) if isinstance(r, dict)]
    ongoing_rows = [r for r in rows if str(r.get("status")) == "Ongoing"]
    if not ongoing_rows:
        pytest.skip("fixture 内无 Ongoing smart_money_cost")
    latest = max(ongoing_rows, key=lambda r: int(r.get("start_time", 0)))

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract(symbol, tf)
    assert snap is not None
    og = snap.smart_money_ongoing
    assert og is not None, "snap 内未识别 Ongoing smart money"
    assert abs(og.avg_price - float(latest["avg_price"])) < 1e-4
    assert og.type == str(latest["type"])


# ════════════════════════════════════════════════════════════════════
# L2-V1.1 · V1.1 扩展 7 个指标的入库一致性黄金断言
# （Feature/规则层接入见 Phase 2/3，本阶段只验证 atoms_* 表里能 1:1 找到关键行）
# ════════════════════════════════════════════════════════════════════


def _require_fixture(snap_dir: Path, name: str) -> dict:
    """V1.1 指标对老快照不存在时直接 skip，不让老快照因此挂。"""
    path = snap_dir / name
    if not path.exists():
        pytest.skip(f"老快照 {snap_dir.name} 无 V1.1 fixture {name}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_latest_choch_event_in_db(
    snap_dir: Path, db, settings, configured_logging
):
    """最新 CHoCH/BOS 事件必然入 atoms_choch_events。

    对应图上最右边那个 ⚡ 标记 —— 必须能从 DB 用 (ts, level_price, type) 精确查到。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _require_fixture(snap_dir, "inst_choch.json")
    rows = [r for r in (raw.get("inst_choch") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture inst_choch 为空")

    latest = max(rows, key=lambda r: int(r.get("timestamp", 0)))
    row = await db.fetchone(
        "SELECT ts, price, level_price, type FROM atoms_choch_events "
        "WHERE symbol=? AND tf=? AND ts=? AND type=? AND level_price=?",
        (
            symbol, tf,
            int(latest["timestamp"]),
            str(latest["type"]),
            float(latest["level_price"]),
        ),
    )
    assert row is not None, (
        f"最新 CHoCH 事件未入库: ts={latest['timestamp']} "
        f"type={latest['type']} level={latest['level_price']}"
    )
    assert abs(float(row["price"]) - float(latest["price"])) < 1e-4


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_strongest_cascade_band_in_db(
    snap_dir: Path, db, settings, configured_logging
):
    """signal_count 最高 or volume 最大的 💣 爆仓带必然入 atoms_cascade_bands。

    对应图上最显眼的红/绿 💣 带 —— 肉眼可验证准确性。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _require_fixture(snap_dir, "cascade_liquidation.json")
    rows = [r for r in (raw.get("order_blocks") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture cascade_liquidation 为空")

    # 优先按 signal_count（爆炸威力）排，fallback volume
    strongest = max(
        rows,
        key=lambda r: (int(r.get("signal_count") or 0), float(r.get("volume") or 0)),
    )
    row = await db.fetchone(
        "SELECT avg_price, volume, signal_count, type, "
        "       bottom_price, top_price "
        "FROM atoms_cascade_bands "
        "WHERE symbol=? AND tf=? AND type=? AND avg_price=?",
        (symbol, tf, str(strongest["type"]), float(strongest["avg_price"])),
    )
    assert row is not None, (
        f"最强 💣 爆仓带未入库: type={strongest['type']} "
        f"avg={strongest['avg_price']} vol={strongest['volume']}"
    )
    assert int(row["signal_count"]) == int(strongest["signal_count"])
    assert abs(float(row["volume"]) - float(strongest["volume"])) < 1e-3
    # 价位结构不能颠倒
    assert float(row["bottom_price"]) <= float(row["avg_price"]) <= float(row["top_price"])


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_ongoing_roi_segment_in_db(
    snap_dir: Path, db, settings, configured_logging
):
    """最新 Ongoing 的 ROI 段必然入 atoms_roi_segments，并且极限目标与 fixture 1:1 一致。

    对应图上当前波段的"亮色极限目标实线" —— 用户最关心的"还能走多远"。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _require_fixture(snap_dir, "trend_roi_exhaustion.json")
    rows = [r for r in (raw.get("trend_roi_exhaustion") or []) if isinstance(r, dict)]
    ongoing = [r for r in rows if str(r.get("status")) == "Ongoing"]
    if not ongoing:
        pytest.skip("fixture trend_roi_exhaustion 内无 Ongoing 段")

    latest = max(ongoing, key=lambda r: int(r.get("start_time", 0)))
    row = await db.fetchone(
        "SELECT avg_price, limit_avg_price, limit_max_price, type, status "
        "FROM atoms_roi_segments "
        "WHERE symbol=? AND tf=? AND start_time=? AND type=?",
        (symbol, tf, int(latest["start_time"]), str(latest["type"])),
    )
    assert row is not None, (
        f"Ongoing ROI 段未入库: start={latest['start_time']} type={latest['type']}"
    )
    assert abs(float(row["limit_max_price"]) - float(latest["limit_max_price"])) < 1e-3
    assert abs(float(row["limit_avg_price"]) - float(latest["limit_avg_price"])) < 1e-3
    assert str(row["status"]) == "Ongoing"


# ════════════════════════════════════════════════════════════════════
# L2-V1.1 · 特征层（FeatureSnapshot）数字化视图一致性黄金断言
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_snap_choch_latest_matches_fixture(
    snap_dir: Path, db, settings, configured_logging
):
    """FeatureSnapshot.choch_latest ↔ fixture 里最新一条 CHoCH 事件 1:1 一致。"""
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _require_fixture(snap_dir, "inst_choch.json")
    rows = [r for r in (raw.get("inst_choch") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture inst_choch 为空")

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract(symbol, tf)
    assert snap is not None

    # features 内按 recent_window_bars（默认 8）截窗；挑 fixture 里符合窗口内最近的一条。
    tf_ms = {"30m": 30 * 60_000, "1h": 60 * 60_000, "4h": 4 * 60 * 60_000}[tf]
    window = int(
        settings.rules_defaults.get("global", {}).get("recent_window_bars", 8)
    )
    cutoff = snap.anchor_ts - window * tf_ms
    windowed = [r for r in rows if int(r.get("timestamp", 0)) >= cutoff]
    if not windowed:
        # 真实 fixture 里若近窗无 CHoCH → snap.choch_latest 应为 None
        assert snap.choch_latest is None
        pytest.skip("fixture 近窗无 CHoCH 事件")

    latest_raw = max(windowed, key=lambda r: int(r["timestamp"]))
    latest = snap.choch_latest
    assert latest is not None
    assert latest.ts == int(latest_raw["timestamp"])
    assert latest.type == str(latest_raw["type"])
    assert abs(latest.price - float(latest_raw["price"])) < 1e-4
    assert abs(latest.level_price - float(latest_raw["level_price"])) < 1e-4
    # 派生：bars_since 非负、direction/kind 与 type 自洽
    assert latest.bars_since >= 0
    assert latest.direction == ("bullish" if latest.type.endswith("Bullish") else "bearish")
    assert latest.kind == ("CHoCH" if latest.type.startswith("CHoCH") else "BOS")


@pytest.mark.asyncio
@pytest.mark.parametrize("snap_dir", _PARAMS)
async def test_golden_snap_cascade_topn_matches_fixture_strongest(
    snap_dir: Path, db, settings, configured_logging
):
    """FeatureSnapshot.cascade_bands TopN 首条 ↔ fixture 里最强的同侧带。

    对应图上最显眼那条 💣（做多/做空二选一按 signal_count 全局最大侧验证）。
    """
    symbol, tf, _ = await _run_collect_once(snap_dir, db, settings)
    raw = _require_fixture(snap_dir, "cascade_liquidation.json")
    rows = [r for r in (raw.get("order_blocks") or []) if isinstance(r, dict)]
    if not rows:
        pytest.skip("fixture cascade_liquidation 为空")

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract(symbol, tf)
    assert snap is not None
    views = snap.cascade_bands
    if not views:
        pytest.skip("snap.cascade_bands 为空")

    # 从 fixture 取全局最强带
    strongest = max(
        rows,
        key=lambda r: (int(r.get("signal_count") or 0), float(r.get("volume") or 0)),
    )
    expected_side = "long_fuel" if strongest["type"] == "Accumulation" else "short_fuel"
    # 取 snap 同侧 TopN 首条（按 SQL 已排过序：signal_count DESC, volume DESC）
    same_side = [v for v in views if v.side == expected_side]
    assert same_side, f"snap 同侧 {expected_side} 带为空"
    top1 = same_side[0]

    assert int(top1.signal_count or 0) == int(strongest["signal_count"])
    assert abs(top1.volume - float(strongest["volume"])) < 1e-3
    assert abs(top1.avg_price - float(strongest["avg_price"])) < 1e-4
    # 价位结构合理
    assert top1.bottom_price <= top1.avg_price <= top1.top_price
    # distance_pct 与 above_price 自洽
    assert (top1.above_price is True) == (top1.distance_pct > 0)

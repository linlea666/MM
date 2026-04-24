"""对真源跑一次 6 模块完整 pipeline，打印所有子模块结果。"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.core.config import load_settings
from backend.rules.features import FeatureExtractor
from backend.rules.modules import (
    build_hero,
    build_key_levels,
    build_liquidity_map,
    build_main_force_radar,
    build_participation,
    build_phase_state,
    build_trade_plan,
)
from backend.rules.scoring import (
    score_accumulation,
    score_breakout,
    score_distribution,
    score_reversal,
)
from backend.storage.db import Database


async def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    tf = sys.argv[2] if len(sys.argv) > 2 else "30m"
    window = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    settings = load_settings()
    settings.rules_defaults["global"]["recent_window_bars"] = window
    cfg = settings.rules_defaults

    db = Database(settings)
    await db.connect()
    try:
        ext = FeatureExtractor(db, config=cfg)
        snap = await ext.extract(symbol, tf)
        if snap is None:
            print(f"[modules] 无数据 {symbol}/{tf}")
            return 1

        caps = {
            "accumulation": score_accumulation(snap, cfg),
            "distribution": score_distribution(snap, cfg),
            "breakout": score_breakout(snap, cfg),
            "reversal": score_reversal(snap, cfg),
        }

        behavior = build_main_force_radar(snap, caps, cfg)
        participation = build_participation(snap, cfg)
        phase = build_phase_state(snap, caps, cfg, participation_level=participation.level)
        levels = build_key_levels(snap, cfg)
        liquidity = build_liquidity_map(snap, cfg)
        plans = build_trade_plan(snap, caps, phase, participation, cfg)
        hero = build_hero(
            behavior=behavior, phase=phase, participation=participation,
            levels=levels, liquidity=liquidity, plans=plans,
        )

        print(f"[{symbol}/{tf}] price={snap.last_price} window={window}")
        print("=" * 60)
        print(f"Hero        : {hero.action_conclusion} ({hero.stars}★)")
        print(f"  behavior  : {hero.main_behavior}")
        print(f"  structure : {hero.market_structure}")
        print(f"  risk      : {hero.risk_status}")
        print(f"  invalid   : {hero.invalidation}")
        print("=" * 60)
        print(f"Behavior  main={behavior.main}({behavior.main_score})")
        print(f"  sub={behavior.sub_scores}")
        print(f"  alerts={[f'{a.type}({a.strength})' for a in behavior.alerts]}")
        print(f"Phase     current={phase.current}({phase.current_score}) next={phase.next_likely} unstable={phase.unstable}")
        print(f"Participation level={participation.level} conf={participation.confidence}")
        for ev in participation.evidence:
            print(f"  · {ev}")
        print("Key Levels:")
        for k in ("r3", "r2", "r1"):
            lv = getattr(levels, k)
            if lv:
                print(f"  {k.upper()}  {lv.price}  {lv.strength}  score={lv.score} sources={lv.sources[:4]}")
        print(f"  --  当前价 {levels.current_price}  --")
        for k in ("s1", "s2", "s3"):
            lv = getattr(levels, k)
            if lv:
                print(f"  {k.upper()}  {lv.price}  {lv.strength}  score={lv.score} sources={lv.sources[:4]}")
        print(
            f"Liquidity   nearest={liquidity.nearest_side}"
            f" dist={round((liquidity.nearest_distance_pct or 0) * 100, 2)}%"
            f" above={len(liquidity.above_targets)} below={len(liquidity.below_targets)}"
        )
        for t in liquidity.above_targets[:3]:
            print(f"  ↑ {t.price}  {t.source:8}  intensity={t.intensity}  dist={round(t.distance_pct*100,2)}%")
        for t in liquidity.below_targets[:3]:
            print(f"  ↓ {t.price}  {t.source:8}  intensity={t.intensity}  dist={round(t.distance_pct*100,2)}%")
        print(f"Plans ({len(plans)}):")
        for p in plans:
            print(f"  [{p.label}] {p.action} {p.stars}★ size={p.position_size}")
            if p.entry:
                print(f"     entry={p.entry} stop={p.stop} tp={p.take_profit}")
            print(f"     premise: {p.premise}")
            print(f"     invalid: {p.invalidation}")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

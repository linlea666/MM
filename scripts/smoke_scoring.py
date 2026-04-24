"""对真源 SQLite 跑一次 4 个 snapshot 级 scorer，打印评分和证据摘要。"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.core.config import load_settings
from backend.rules.features import FeatureExtractor
from backend.rules.scoring import (
    score_accumulation,
    score_breakout,
    score_distribution,
    score_reversal,
)
from backend.storage.db import Database


def _dump_cap(cap):
    def short_ev(e):
        return {
            "rule": e.rule_id,
            "label": e.label,
            "hit": e.hit,
            "ratio": round(e.ratio, 3),
            "contribution": round(e.contribution, 2),
            "value": e.value,
            "threshold": e.threshold,
            "note": e.note,
        }
    return {
        "name": cap.name,
        "score": cap.score,
        "band": cap.band,
        "direction": cap.direction,
        "evidence": [short_ev(e) for e in cap.evidence],
    }


async def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    tf = sys.argv[2] if len(sys.argv) > 2 else "30m"
    window = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    settings = load_settings()
    settings.rules_defaults["global"]["recent_window_bars"] = window
    db = Database(settings)
    await db.connect()
    try:
        ext = FeatureExtractor(db, config=settings.rules_defaults)
        snap = await ext.extract(symbol, tf)
        if snap is None:
            print(f"[scoring] 无数据 {symbol}/{tf}")
            return 1
        cfg = settings.rules_defaults
        caps = [
            score_accumulation(snap, cfg),
            score_distribution(snap, cfg),
            score_breakout(snap, cfg),
            score_reversal(snap, cfg),
        ]
        print(f"[scoring] {symbol}/{tf} @ anchor_ts={snap.anchor_ts} price={snap.last_price}")
        print(f"[scoring] window={window} imb_green={snap.imbalance_green_ratio:.2f} "
              f"imb_red={snap.imbalance_red_ratio:.2f} reson={snap.resonance_count_recent} "
              f"sweep={snap.sweep_count_recent} broke_r={snap.just_broke_resistance} "
              f"broke_s={snap.just_broke_support}")
        for c in caps:
            print(f"  - {c.name:14} score={c.score:5.2f} band={c.band:12} dir={c.direction}")
        print()
        print(json.dumps({c.name: _dump_cap(c) for c in caps}, ensure_ascii=False, indent=2))
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

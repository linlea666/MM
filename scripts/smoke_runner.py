"""RuleRunner 端到端 smoke：真源 SQLite → DashboardSnapshot。"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.core.config import load_settings
from backend.rules import NoDataError, RuleRunner
from backend.storage.db import Database


async def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    tf = sys.argv[2] if len(sys.argv) > 2 else "30m"
    window = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    settings = load_settings()
    settings.rules_defaults["global"]["recent_window_bars"] = window

    db = Database(settings)
    await db.connect()
    try:
        runner = RuleRunner(db, config=settings.rules_defaults)
        try:
            dash = await runner.run(symbol, tf)
        except NoDataError as e:
            print(f"[runner] NoDataError: {e}")
            return 1

        print(f"[{dash.symbol}/{dash.tf}] ts={dash.timestamp} price={dash.current_price}")
        print("─" * 60)
        print("HERO:")
        print(f"  behavior  : {dash.hero.main_behavior}")
        print(f"  structure : {dash.hero.market_structure}")
        print(f"  risk      : {dash.hero.risk_status}")
        print(f"  action    : {dash.hero.action_conclusion} ({dash.hero.stars}★)")
        print(f"  invalid   : {dash.hero.invalidation}")
        print("─" * 60)
        print(f"Behavior  main={dash.behavior.main}({dash.behavior.main_score})  sub={dash.behavior.sub_scores}")
        print(f"  alerts={[f'{a.type}({a.strength})' for a in dash.behavior.alerts]}")
        print(f"Phase     current={dash.phase.current}({dash.phase.current_score}) next={dash.phase.next_likely} unstable={dash.phase.unstable}")
        print(f"Participation  level={dash.participation.level}  conf={dash.participation.confidence}")
        print(f"Capabilities ({len(dash.capability_scores)}):")
        for c in dash.capability_scores:
            print(f"  · {c.name:14} {c.score:3d} conf={c.confidence}  [{c.notes}]")
            for e in c.evidences[:3]:
                print(f"      - {e}")
        print(f"Plans ({len(dash.plans)}):")
        for p in dash.plans:
            print(f"  [{p.label}] {p.action} {p.stars}★  size={p.position_size}")
            if p.entry:
                print(f"      entry={p.entry} stop={p.stop} tp={p.take_profit}")
        print(f"Timeline ({len(dash.recent_events)}):")
        for ev in dash.recent_events:
            print(f"  · [{ev.severity:7}] ts={ev.ts}  {ev.kind:15}  {ev.headline}")
        print(f"Health    fresh={dash.health.fresh}  last_ts={dash.health.last_collector_ts}  stale_s={dash.health.stale_seconds}")
        if dash.health.warnings:
            print(f"  warnings: {dash.health.warnings}")

        # 验证 Pydantic 序列化（API 层会用）
        payload = dash.model_dump(mode="json")
        print("─" * 60)
        print(f"[runner] model_dump(json) OK, size={len(json.dumps(payload))} bytes")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

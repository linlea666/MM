"""对 smoke_collect 落地后的 SQLite 直接跑一次 FeatureExtractor，打印快照摘要。"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.core.config import load_settings
from backend.rules.features import FeatureExtractor
from backend.storage.db import Database


async def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    tf = sys.argv[2] if len(sys.argv) > 2 else "30m"

    settings = load_settings()
    db = Database(settings)
    await db.connect()
    try:
        ext = FeatureExtractor(db, config=settings.rules_defaults)
        snap = await ext.extract(symbol, tf)
        if snap is None:
            print(f"[features] 无数据 {symbol}/{tf}")
            return 1
        data = snap.model_dump(mode="json")

        # 只展示关键派生字段
        summary = {
            "symbol": snap.symbol,
            "tf": snap.tf,
            "anchor_ts": snap.anchor_ts,
            "last_price": snap.last_price,
            "atr": round(snap.atr or 0, 2),
            "vwap_last": snap.vwap_last,
            "vwap_slope_pct": round((snap.vwap_slope or 0) * 100, 3),
            "fair_value_delta_pct": round((snap.fair_value_delta_pct or 0) * 100, 3),
            "cvd_slope": snap.cvd_slope,
            "cvd_sign": snap.cvd_slope_sign,
            "imb_green_ratio": round(snap.imbalance_green_ratio, 3),
            "imb_red_ratio": round(snap.imbalance_red_ratio, 3),
            "poc_trend": snap.poc_shift_trend,
            "poc_delta_pct": round((snap.poc_shift_delta_pct or 0) * 100, 3),
            "resonance_count_recent": snap.resonance_count_recent,
            "resonance_buy": snap.resonance_buy_count,
            "resonance_sell": snap.resonance_sell_count,
            "whale_net_direction": snap.whale_net_direction,
            "sweep_count_recent": snap.sweep_count_recent,
            "trend_exhaustion": snap.trend_exhaustion_last.exhaustion if snap.trend_exhaustion_last else None,
            "trend_exhaustion_type": snap.trend_exhaustion_last.type if snap.trend_exhaustion_last else None,
            "trend_saturation_progress": snap.trend_saturation.progress if snap.trend_saturation else None,
            "current_hour_activity": round(snap.current_hour_activity, 3),
            "active_session": snap.active_session,
            "hvn_nodes": len(snap.hvn_nodes),
            "absolute_zones": len(snap.absolute_zones),
            "order_blocks": len(snap.order_blocks),
            "micro_pocs": len(snap.micro_pocs),
            "vacuums": len(snap.vacuums),
            "heatmap_bands": len(snap.heatmap),
            "liq_fuel": len(snap.liquidation_fuel),
            "nearest_support": snap.nearest_support_price,
            "nearest_support_dist_pct": round((snap.nearest_support_distance_pct or 0) * 100, 3),
            "nearest_resistance": snap.nearest_resistance_price,
            "nearest_resistance_dist_pct": round((snap.nearest_resistance_distance_pct or 0) * 100, 3),
            "just_broke_resistance": snap.just_broke_resistance,
            "just_broke_support": snap.just_broke_support,
            "stale_tables": snap.stale_tables,
        }
        print("[features] summary:")
        print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

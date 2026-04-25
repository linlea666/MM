"""V1.1 · 指标全景 REST。

设计：直接把 ``FeatureSnapshot`` 序列化输出。前端按"分类映射表"渲染成 5 大族：
- 趋势族：trend_* / cvd_* / poc_shift_*
- 价值带族：hvn_nodes / absolute_zones / order_blocks / volume_profile / micro_pocs
- 流动性族：vacuums / heatmap / liquidation_fuel / cascade_bands / retail_stop_bands /
  liq_recovery 系列
- 结构事件族：choch_latest/recent / sweep_last/count / power_imbalance / trend_exhaustion
- 主力族：smart_money_ongoing/all / resonance_* / whale_* / trailing_vwap_last

不做新 model 包装：FeatureSnapshot 已是 Pydantic v2，
``model_dump`` 的形状即 schema；前端 TS 类型跟着走。

为什么不复用 /api/dashboard：
- /api/dashboard 走 2s TTL 缓存，体积固定（决策视图）；
- /api/indicators 是"调参/复盘"用，体积大但访问频次低（用户进抽屉时才拉）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import (
    get_rule_runner,
    get_sub_repo,
    resolve_active_symbol,
)
from backend.core.exceptions import NoDataError
from backend.core.logging import Tags
from backend.core.timeframes import DEFAULT_TF, SupportedTf
from backend.rules import RuleRunner
from backend.storage.repositories import SubscriptionRepository

logger = logging.getLogger("api.indicators")

router = APIRouter(prefix="/api", tags=["indicators"])


@router.get("/indicators")
async def get_indicators_panorama(
    symbol: str | None = Query(
        None, description="币种代码（不传则取首个 active 订阅）"
    ),
    tf: SupportedTf = Query(  # type: ignore[valid-type]
        DEFAULT_TF, description="周期：30m / 1h / 4h"
    ),
    runner: RuleRunner = Depends(get_rule_runner),
    sub_repo: SubscriptionRepository = Depends(get_sub_repo),
) -> dict:
    """返回 FeatureSnapshot 全字段 dump，前端按分类映射表渲染。"""
    resolved_symbol = await resolve_active_symbol(symbol, sub_repo)
    try:
        snap = await runner._ext.extract(resolved_symbol, tf)
    except NoDataError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail=f"{resolved_symbol}/{tf} 无可用 FeatureSnapshot",
        )

    payload = snap.model_dump()
    logger.debug(
        "indicators panorama generated",
        extra={
            "tags": [Tags.DASHBOARD, Tags.API],
            "context": {
                "symbol": resolved_symbol,
                "tf": tf,
                "stale_tables": payload.get("stale_tables", []),
            },
        },
    )
    return payload

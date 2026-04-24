"""V1.1 · 周期/币种单一真源（后端硬白名单）。

设计动机（"Phase 4 · 周期单一真源"）：
- 历史遗留：``normalize_tf`` 白名单宽到 5m/15m/2h/1d，但 ``collector.timeframes``
  只采集 30m/1h/4h。结果是前端能发 ``tf=5m``、后端接受后规则引擎空跑、
  快照既无数据也不报错，排障困难。
- 结论：把 **实际支持的 tf** 收敛到一处常量，所有边界校验（REST Query、WS
  action、缓存清理循环、前端 Select）都读这里，前后端永远对齐。

Symbol 侧同款治理：
- 白名单 = **订阅表中的 active symbol**（V1.1 默认只有 BTC）。
- 用户若要交易 ETH，在前端 /subscriptions 添加即可，白名单随之扩展；
  yaml ``collector.default_symbols`` 仅影响首次落库。
- API 层直接 404 ``NO_ACTIVE_SUBSCRIPTION``，而不是静默空响应。

这里只放常量与类型，不引入任何 runtime 依赖；``normalize_tf`` 等函数仍放
``backend/api/deps.py`` 内使用本模块，避免循环导入。
"""

from __future__ import annotations

from typing import Literal, get_args

# ─── 业务 tf（与 collector.timeframes、rules 引擎口径一致） ─────────

SupportedTf = Literal["30m", "1h", "4h"]
"""Dashboard / 规则引擎 / API / WS 唯一认可的 tf 集合。"""

SUPPORTED_TFS: tuple[SupportedTf, ...] = get_args(SupportedTf)  # type: ignore[assignment]
"""``SupportedTf`` 的 runtime 元组形式（用于 ``in`` 判断与 FastAPI 错误提示）。"""

DEFAULT_TF: SupportedTf = "30m"
"""默认 tf（前端首次进入 / 未带 query 时兜底）。"""


def is_supported_tf(tf: str) -> bool:
    """只用来做 ``if`` 判断；想抛错请用 ``deps.normalize_tf``。"""
    return tf in SUPPORTED_TFS


__all__ = [
    "DEFAULT_TF",
    "SUPPORTED_TFS",
    "SupportedTf",
    "is_supported_tf",
]

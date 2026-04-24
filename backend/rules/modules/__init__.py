"""6 个模块 builder：把 FeatureSnapshot + CapabilityScore 组装成 DashboardSnapshot 各子模块。"""

from .hero import build_hero
from .key_levels import build_key_levels
from .liquidity_map import build_liquidity_map
from .main_force_radar import build_main_force_radar
from .participation import build_participation
from .phase_state import build_phase_state
from .trade_plan import build_trade_plan

__all__ = [
    "build_hero",
    "build_key_levels",
    "build_liquidity_map",
    "build_main_force_radar",
    "build_participation",
    "build_phase_state",
    "build_trade_plan",
]

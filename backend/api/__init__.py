"""FastAPI 路由层。

按资源维度拆分路由文件：
- ``dashboard``     RuleRunner 驱动的大屏快照
- ``subscriptions`` 订阅 CRUD（SubscriptionManager 暴露）
- ``system``        系统健康 / 运行状态

所有错误通过 ``MMError`` 体系翻译为 HTTP 状态码，无鉴权（V1 内网部署）。
"""

from .ai_router import router as ai_router
from .config_router import router as config_router
from .dashboard import router as dashboard_router
from .indicators_router import router as indicators_router
from .logs_router import router as logs_router
from .momentum_pulse import router as momentum_pulse_router
from .subscriptions import router as subscriptions_router
from .system import router as system_router
from .ws_routes import router as ws_router

__all__ = [
    "ai_router",
    "config_router",
    "dashboard_router",
    "indicators_router",
    "logs_router",
    "momentum_pulse_router",
    "subscriptions_router",
    "system_router",
    "ws_router",
]

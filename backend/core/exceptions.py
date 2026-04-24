"""统一异常类型。

所有跨模块抛出的异常都应继承自 MMError，便于在 API 层统一处理。
"""

from __future__ import annotations


class MMError(Exception):
    """MM 项目所有自定义异常的基类。"""

    code: str = "MM_ERROR"
    http_status: int = 500

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
            }
        }


class ConfigError(MMError):
    code = "CONFIG_ERROR"
    http_status = 500


class ConfigKeyNotAllowedError(ConfigError):
    """尝试修改的 key 不在 Tier 1 白名单中。"""

    code = "CONFIG_KEY_NOT_ALLOWED"
    http_status = 400


class ConfigValueInvalidError(ConfigError):
    """值不满足 meta 约束（类型/范围/枚举）。"""

    code = "CONFIG_VALUE_INVALID"
    http_status = 400


class StorageError(MMError):
    code = "STORAGE_ERROR"
    http_status = 500


class CollectorError(MMError):
    code = "COLLECTOR_ERROR"
    http_status = 502


class HFDError(CollectorError):
    code = "HFD_ERROR"
    http_status = 502


class ExchangeError(CollectorError):
    code = "EXCHANGE_ERROR"
    http_status = 502


class ParseError(CollectorError):
    code = "PARSE_ERROR"
    http_status = 500


class SubscriptionError(MMError):
    code = "SUBSCRIPTION_ERROR"
    http_status = 400


class SymbolNotFoundError(SubscriptionError):
    code = "SYMBOL_NOT_FOUND"
    http_status = 404


class SymbolAlreadyExistsError(SubscriptionError):
    code = "SYMBOL_ALREADY_EXISTS"
    http_status = 409


class RuleError(MMError):
    code = "RULE_ERROR"
    http_status = 500


class NoDataError(RuleError):
    """RuleRunner / FeatureExtractor 无数据可用（API 层 → 404）。"""

    code = "NO_DATA"
    http_status = 404


class AIError(MMError):
    code = "AI_ERROR"
    http_status = 502

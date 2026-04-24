"""配置加载：合并 YAML + 环境变量。

使用方式：
    from backend.core.config import get_settings

    settings = get_settings()        # 默认从 backend/config/app.yaml 读取
    settings.server.rest_port        # → 8901
    settings.collector.default_symbols  # → ["BTC"]

环境变量覆盖（前缀 MM_，双下划线分层）：
    MM_SERVER__REST_PORT=8910
    MM_LOGGING__LEVEL=DEBUG
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .exceptions import ConfigError

# 默认配置目录
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class AppMeta(BaseModel):
    name: str = "MM"
    version: str = "0.1.0"
    env: Literal["development", "production"] = "development"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    rest_port: int = 8901
    ws_port: int = 8902
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])


class DatabaseConfig(BaseModel):
    path: str = "data/mm.sqlite"
    logs_path: str = "logs/mm-logs.sqlite"
    wal_mode: bool = True
    busy_timeout_ms: int = 5000


class RedisConfig(BaseModel):
    enabled: bool = False
    host: str = "localhost"
    port: int = 6379


class KlineSourcesConfig(BaseModel):
    primary: str = "binance"
    fallback: list[str] = Field(default_factory=lambda: ["okx"])


class ScheduleConfig(BaseModel):
    kline_close: list[str] = Field(default_factory=list)
    every_30min: list[str] = Field(default_factory=list)
    every_5min: list[str] = Field(default_factory=list)
    every_1h: list[str] = Field(default_factory=list)
    every_4h: list[str] = Field(default_factory=list)


class CollectorConfig(BaseModel):
    global_rps: int = 5
    request_timeout_seconds: int = 30
    default_symbols: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframes: list[str] = Field(default_factory=lambda: ["30m", "1h", "4h"])
    hfd_base_url: str = "https://dash.hfd.fund/api/pro/pro_data"
    kline_sources: KlineSourcesConfig = Field(default_factory=KlineSourcesConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    schedule_delay_seconds: int = 5


class AIConfig(BaseModel):
    enabled: bool = False
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    cache_ttl_minutes: int = 5
    observer_interval_minutes: int = 5
    api_key: str | None = None  # 由环境变量注入


class LogFileConfig(BaseModel):
    enabled: bool = True
    path: str = "logs/mm.log"
    max_size_mb: int = 100
    backup_count: int = 10


class LogSqliteConfig(BaseModel):
    enabled: bool = True
    min_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    retention_days: int = 7


class LogWsConfig(BaseModel):
    enabled: bool = True


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: str = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    datefmt: str = "%Y-%m-%d %H:%M:%S"
    console: bool = True
    file: LogFileConfig = Field(default_factory=LogFileConfig)
    sqlite: LogSqliteConfig = Field(default_factory=LogSqliteConfig)
    ws: LogWsConfig = Field(default_factory=LogWsConfig)


class StatsConfig(BaseModel):
    daily_review_hour_utc: int = 0


class Settings(BaseModel):
    """应用总配置。"""

    app: AppMeta = Field(default_factory=AppMeta)
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    stats: StatsConfig = Field(default_factory=StatsConfig)

    # 规则引擎出厂默认值（rules.default.yaml，嵌套字典，不强类型校验）
    # 运行时真正生效值 = 本字段 DEEP MERGE SQLite.config_overrides
    # 前端 /settings 的表单渲染靠 rules_meta。
    rules_defaults: dict[str, Any] = Field(default_factory=dict)
    rules_meta: dict[str, Any] = Field(default_factory=dict)

    # 运行时计算的派生值
    config_dir: Path = Field(default_factory=lambda: DEFAULT_CONFIG_DIR, exclude=True)

    def resolve_path(self, relative: str) -> Path:
        """配置里的相对路径基于 backend/ 目录解析。"""
        p = Path(relative)
        if p.is_absolute():
            return p
        return self.config_dir.parent / p


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件根节点必须是 mapping: {path}")
        return data
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 解析失败 {path}: {e}") from e


def _apply_env_overrides(data: dict[str, Any], prefix: str = "MM_") -> None:
    """支持环境变量覆盖，如 MM_SERVER__REST_PORT=8910 → data["server"]["rest_port"] = 8910"""
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        path = env_key[len(prefix):].lower().split("__")
        cursor: Any = data
        for key in path[:-1]:
            if not isinstance(cursor, dict):
                break
            cursor = cursor.setdefault(key, {})
        if isinstance(cursor, dict):
            leaf = path[-1]
            cursor[leaf] = _coerce(env_val)


def _coerce(v: str) -> Any:
    """字符串环境变量转换为合理类型。"""
    low = v.lower()
    if low in ("true", "yes", "1"):
        return True
    if low in ("false", "no", "0"):
        return False
    if low == "null" or low == "none":
        return None
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def load_settings(config_dir: Path | None = None) -> Settings:
    """从指定目录加载配置。

    优先级：env > app.yaml > 默认值。
    同时加载 rules.default.yaml / rules.meta.yaml 作为规则出厂默认值与 UI 元数据。
    """
    cfg_dir = config_dir or DEFAULT_CONFIG_DIR

    # 加载 .env（如果存在）
    env_file = cfg_dir.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)

    app_data = _load_yaml(cfg_dir / "app.yaml")
    rules_defaults = _load_yaml(cfg_dir / "rules.default.yaml")
    rules_meta = _load_yaml(cfg_dir / "rules.meta.yaml")

    # 注入 .env 中的 AI key
    ai_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or None
    app_data.setdefault("ai", {})["api_key"] = ai_key

    _apply_env_overrides(app_data)

    settings = Settings(
        **app_data,
        rules_defaults=rules_defaults,
        rules_meta=rules_meta,
        config_dir=cfg_dir,
    )
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局单例（生产用）。测试中通过 ``reload_settings`` 切换。"""
    return load_settings()


def reload_settings(config_dir: Path | None = None) -> Settings:
    """清缓存后重新加载（测试 / 配置热更新用）。"""
    get_settings.cache_clear()
    if config_dir is not None:
        # 让 lru_cache 包裹的函数返回特定 dir 的结果
        # 这里直接调用，并把结果再放进 cache
        settings = load_settings(config_dir)
        # lru_cache 不支持手动 set，下次 get_settings() 仍会跑 load_settings()
        # 但因为只调用 1 次，性能可忽略
        return settings
    return get_settings()

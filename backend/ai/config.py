"""V1.1 · Phase 9 · AI 观察器运行时配置。

把 rules config 的 ``ai.*`` 子树映射成强类型 ``AIRuntimeConfig``。
读取流水（优先级从高到低）：
1. rules_config_svc.snapshot()["ai"]（用户通过 /settings 面板编辑）
2. Settings.ai（app.yaml）
3. 默认值（下方 dataclass）

所有 secret 字段（api_key）永远不 log 原文，只能 mask 后输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AIRuntimeConfig:
    """AI observer 的完整运行时配置。

    V1.1 · 模型策略：
    - ``model_tier`` = "flash" | "pro"：**全局单一模型**（三层都用它），
      用户在 /settings 选择；默认 flash（低成本、低延迟）。
    - ``thinking_enabled`` = false（默认）→ DeepSeek V4 thinking mode 关闭，
      保持 ``response_format=json_object``，输出稳定可解析；
      true → 打开 thinking（官方明确 thinking 与 json_object "不可组合"，
      provider 会自动去掉 json_object 强约束 + 去掉 temperature 等 thinking 不支持的参数）。
    """

    enabled: bool = False
    provider: str = "deepseek"        # "deepseek" | "stub"
    api_key: str = ""                 # secret
    base_url: str = "https://api.deepseek.com"

    # 模型选择（全局单一）
    model_tier: str = "flash"         # "flash" | "pro"
    thinking_enabled: bool = False    # 官方：thinking + json_object 不可组合

    # 具体模型名（expert 字段：可覆盖官方默认）
    flash_model: str = "deepseek-v4-flash"
    pro_model: str = "deepseek-v4-pro"
    proxy: str | None = None

    # 触发控制
    min_interval_seconds: int = 180
    cache_ttl_seconds: int = 300

    # 升级控制（阈值仍生效：即便全 flash，L3 是否跑也受阈值 gated）
    auto_trade_plan: bool = True
    auto_trend_confidence: float = 0.70
    auto_money_flow_confidence: float = 0.60

    # 超时 / 温度（按 tier 选：flash 用 flash 一组，pro 用 pro 一组；thinking=true 时 timeout 自动 x2）
    timeout_s_flash: float = 20.0
    timeout_s_pro: float = 45.0
    temperature_flash: float = 0.2
    temperature_pro: float = 0.15

    # 存储
    history_ring_size: int = 50
    jsonl_relpath: str = "data/ai_observations.jsonl"

    @property
    def api_key_masked(self) -> str:
        """生成 mask 显示用的 key（头 3 尾 4，中间 ****）。"""
        return mask_secret(self.api_key)

    def to_audit_dict(self) -> dict[str, Any]:
        """用于审计日志 / 诊断接口的可序列化 dict（api_key 已 mask）。"""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "api_key": self.api_key_masked,
            "base_url": self.base_url,
            "model_tier": self.model_tier,
            "thinking_enabled": self.thinking_enabled,
            "flash_model": self.flash_model,
            "pro_model": self.pro_model,
            "proxy": self.proxy or "",
            "min_interval_seconds": self.min_interval_seconds,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "auto_trade_plan": self.auto_trade_plan,
            "auto_trend_confidence": self.auto_trend_confidence,
            "auto_money_flow_confidence": self.auto_money_flow_confidence,
            "timeout_s_flash": self.timeout_s_flash,
            "timeout_s_pro": self.timeout_s_pro,
            "history_ring_size": self.history_ring_size,
            "jsonl_relpath": self.jsonl_relpath,
        }


def mask_secret(value: str | None) -> str:
    """mask 规则：
    - None / 空串 → ""（空，前端可提示 "尚未配置"）
    - 长度 ≤ 4  → "****"
    - 长度 5-8  → 前 1 位 + **** + 末 2 位
    - 长度 >8   → 前 3 位 + **** + 末 4 位
    """
    if not value:
        return ""
    n = len(value)
    if n <= 4:
        return "****"
    if n <= 8:
        return f"{value[:1]}****{value[-2:]}"
    return f"{value[:3]}****{value[-4:]}"


def build_from_rules(
    rules_snapshot: dict[str, Any],
    *,
    fallback_api_key: str | None = None,
    fallback_base_url: str | None = None,
) -> AIRuntimeConfig:
    """从 rules_config_svc.snapshot() 构造 AIRuntimeConfig。

    - ``rules_snapshot["ai"]`` 不存在时全部走默认；
    - ``fallback_api_key`` / ``fallback_base_url``：用于兼容 ``settings.ai`` 老字段，
      仅当 rules 里没配置时才使用。
    """
    ai_cfg = (rules_snapshot or {}).get("ai") or {}
    observer_cfg = ai_cfg.get("observer", {}) or {}
    storage_cfg = ai_cfg.get("storage", {}) or {}

    model_tier_raw = str(ai_cfg.get("model_tier", "flash")).lower().strip()
    if model_tier_raw not in ("flash", "pro"):
        model_tier_raw = "flash"

    return AIRuntimeConfig(
        enabled=bool(ai_cfg.get("enabled", False)),
        provider=str(ai_cfg.get("provider", "deepseek")),
        api_key=str(ai_cfg.get("api_key") or fallback_api_key or ""),
        base_url=str(ai_cfg.get("base_url") or fallback_base_url or "https://api.deepseek.com"),
        model_tier=model_tier_raw,
        thinking_enabled=bool(ai_cfg.get("thinking_enabled", False)),
        flash_model=str(ai_cfg.get("flash_model", "deepseek-v4-flash")),
        pro_model=str(ai_cfg.get("pro_model", "deepseek-v4-pro")),
        proxy=(ai_cfg.get("proxy") or None),
        min_interval_seconds=int(observer_cfg.get("min_interval_seconds", 180)),
        cache_ttl_seconds=int(observer_cfg.get("cache_ttl_seconds", 300)),
        auto_trade_plan=bool(observer_cfg.get("auto_trade_plan", True)),
        auto_trend_confidence=float(observer_cfg.get("auto_trend_confidence", 0.70)),
        auto_money_flow_confidence=float(observer_cfg.get("auto_money_flow_confidence", 0.60)),
        timeout_s_flash=float(observer_cfg.get("timeout_s_flash", 20.0)),
        timeout_s_pro=float(observer_cfg.get("timeout_s_pro", 45.0)),
        temperature_flash=float(observer_cfg.get("temperature_flash", 0.2)),
        temperature_pro=float(observer_cfg.get("temperature_pro", 0.15)),
        history_ring_size=int(storage_cfg.get("history_ring_size", 50)),
        jsonl_relpath=str(storage_cfg.get("jsonl_relpath", "data/ai_observations.jsonl")),
    )

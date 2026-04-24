"""V1.1 · Phase 9 · AI 观察层生命周期服务。

``AIObservationService`` 作为 main.py 的单一入口：
- ``build()``：从 rules_config_svc.snapshot() 构造 provider + observer + store；
- ``reload()``：配置热更新时，重建 provider（如 api_key 变更）并替换 observer.settings；
- ``aclose()``：关闭底层 httpx 客户端。

这层存在的理由：main.py 本身已经很长，避免在 lifespan 里塞条件分支。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.ai.config import AIRuntimeConfig, build_from_rules
from backend.ai.observer import AIObserver, ObserverSettings
from backend.ai.providers import DeepSeekProvider, LLMProvider, StubProvider
from backend.ai.storage import AIObservationStore

logger = logging.getLogger("ai.service")


class AIObservationService:
    """一体化服务：provider + observer + store。"""

    def __init__(
        self,
        *,
        data_dir: Path,
        rules_snapshot: dict[str, Any],
        fallback_api_key: str | None = None,
        fallback_base_url: str | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._cfg = build_from_rules(
            rules_snapshot,
            fallback_api_key=fallback_api_key,
            fallback_base_url=fallback_base_url,
        )
        self._provider: LLMProvider = self._make_provider(self._cfg)
        self._store = AIObservationStore(
            ring_size=self._cfg.history_ring_size,
            jsonl_path=self._resolve_jsonl_path(self._cfg.jsonl_relpath),
        )
        self._observer = AIObserver(
            provider=self._provider,
            store=self._store,
            settings=_to_observer_settings(self._cfg),
        )

    # ── 构造辅助 ────────────────────────────────────────────

    def _resolve_jsonl_path(self, relpath: str) -> Path | None:
        if not relpath:
            return None
        p = Path(relpath)
        if not p.is_absolute():
            p = (self._data_dir / relpath).resolve()
        return p

    def _make_provider(self, cfg: AIRuntimeConfig) -> LLMProvider:
        if not cfg.enabled:
            logger.info("AI observer disabled，使用 StubProvider", extra={"tags": ["AI"]})
            return StubProvider(fixtures={})
        if cfg.provider == "stub":
            return StubProvider(fixtures={})
        if cfg.provider == "deepseek":
            if not cfg.api_key:
                logger.warning(
                    "AI provider=deepseek 但 api_key 为空 → 降级为 StubProvider",
                    extra={"tags": ["AI"]},
                )
                return StubProvider(fixtures={})
            try:
                return DeepSeekProvider(
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    flash_model=cfg.flash_model,
                    pro_model=cfg.pro_model,
                    proxy=cfg.proxy,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"DeepSeekProvider 初始化失败，降级为 StubProvider：{e}",
                    extra={"tags": ["AI"]},
                )
                return StubProvider(fixtures={})
        logger.warning(
            f"未知 AI provider={cfg.provider}，降级为 StubProvider",
            extra={"tags": ["AI"]},
        )
        return StubProvider(fixtures={})

    # ── 公共访问 ────────────────────────────────────────────

    @property
    def observer(self) -> AIObserver:
        return self._observer

    @property
    def store(self) -> AIObservationStore:
        return self._store

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def config(self) -> AIRuntimeConfig:
        return self._cfg

    # ── 生命周期 ────────────────────────────────────────────

    async def startup(self) -> None:
        """启动时回灌 jsonl 最近 N 条。"""
        loaded = await self._store.load_tail_from_jsonl(limit=self._cfg.history_ring_size)
        logger.info(
            f"AI observer 启动 enabled={self._cfg.enabled} provider={self._cfg.provider} "
            f"jsonl_loaded={loaded}",
            extra={"tags": ["AI"], "context": self._cfg.to_audit_dict()},
        )

    async def reload(
        self,
        *,
        rules_snapshot: dict[str, Any],
        fallback_api_key: str | None = None,
        fallback_base_url: str | None = None,
    ) -> None:
        """rules config 热更新 → 重建 provider + 更新 observer settings。"""
        new_cfg = build_from_rules(
            rules_snapshot,
            fallback_api_key=fallback_api_key,
            fallback_base_url=fallback_base_url,
        )
        # 关旧 provider
        old_provider = self._provider
        self._cfg = new_cfg
        self._provider = self._make_provider(new_cfg)
        self._observer._provider = self._provider  # 直接替换，避免重建 observer 丢历史
        self._observer._settings = _to_observer_settings(new_cfg)
        # store ring_size 和 jsonl path 可能变
        if (
            self._store.size() == 0
            and self._resolve_jsonl_path(new_cfg.jsonl_relpath) != self._store._jsonl_path
        ):
            self._store = AIObservationStore(
                ring_size=new_cfg.history_ring_size,
                jsonl_path=self._resolve_jsonl_path(new_cfg.jsonl_relpath),
            )
            self._observer._store = self._store
        try:
            await old_provider.aclose()
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "AI observer reloaded",
            extra={"tags": ["AI"], "context": new_cfg.to_audit_dict()},
        )

    async def aclose(self) -> None:
        try:
            await self._provider.aclose()
        except Exception:  # noqa: BLE001
            pass


def _to_observer_settings(cfg: AIRuntimeConfig) -> ObserverSettings:
    return ObserverSettings(
        enabled=cfg.enabled,
        min_interval_seconds=cfg.min_interval_seconds,
        cache_ttl_seconds=cfg.cache_ttl_seconds,
        model_tier=cfg.model_tier,
        thinking_enabled=cfg.thinking_enabled,
        auto_trade_plan=cfg.auto_trade_plan,
        auto_trend_confidence=cfg.auto_trend_confidence,
        auto_money_flow_confidence=cfg.auto_money_flow_confidence,
        timeout_s_flash=cfg.timeout_s_flash,
        timeout_s_pro=cfg.timeout_s_pro,
        temperature_flash=cfg.temperature_flash,
        temperature_pro=cfg.temperature_pro,
    )

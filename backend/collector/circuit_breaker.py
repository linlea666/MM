"""简易熔断器。

触发条件：连续失败 ``threshold`` 次。
冷却 ``cooldown_seconds`` 后半开试探一次，成功则 reset，失败则继续冷却。

注：每个 (service, key) 组合独立计数。service 是 "hfd" / "binance" / "okx"，
key 可以是 endpoint 名或 symbol，由调用方决定粒度。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from backend.core.logging import Tags, get_logger

logger = get_logger("collector.circuit_breaker")


@dataclass
class _State:
    failures: int = 0
    opened_at: float = 0.0
    last_trigger_ts: float = 0.0


@dataclass
class CircuitBreaker:
    """(service, key) 粒度熔断。"""

    threshold: int = 3
    cooldown_seconds: float = 60.0
    states: dict[tuple[str, str], _State] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def is_open(self, service: str, key: str) -> bool:
        with self._lock:
            st = self.states.get((service, key))
            if st is None or st.opened_at == 0:
                return False
            if time.monotonic() - st.opened_at >= self.cooldown_seconds:
                return False
            return True

    def record_success(self, service: str, key: str) -> None:
        with self._lock:
            st = self.states.get((service, key))
            if st is None:
                return
            if st.failures > 0 or st.opened_at > 0:
                logger.info(
                    f"熔断恢复 {service}:{key}",
                    extra={
                        "tags": [Tags.CIRCUIT],
                        "context": {"service": service, "key": key},
                    },
                )
            st.failures = 0
            st.opened_at = 0.0

    def record_failure(self, service: str, key: str, *, reason: str = "") -> bool:
        """返回是否新触发熔断。"""
        with self._lock:
            st = self.states.setdefault((service, key), _State())
            st.failures += 1
            st.last_trigger_ts = time.time()
            just_tripped = False
            if st.failures >= self.threshold and st.opened_at == 0:
                st.opened_at = time.monotonic()
                just_tripped = True
        if just_tripped:
            logger.error(
                f"熔断触发 {service}:{key} 连续失败 {self.threshold} 次 ({reason})",
                extra={
                    "tags": [Tags.CIRCUIT, Tags.URGENT],
                    "context": {
                        "service": service,
                        "key": key,
                        "reason": reason,
                        "cooldown_seconds": self.cooldown_seconds,
                    },
                },
            )
        return just_tripped

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "service": svc,
                    "key": key,
                    "failures": st.failures,
                    "open": st.opened_at > 0,
                    "last_trigger_ts": st.last_trigger_ts,
                }
                for (svc, key), st in self.states.items()
            ]

"""熔断器测试。"""

from __future__ import annotations

import time

from backend.collector.circuit_breaker import CircuitBreaker


def test_threshold_trips(configured_logging):
    cb = CircuitBreaker(threshold=3, cooldown_seconds=0.5)
    for i in range(2):
        tripped = cb.record_failure("hfd", "smart_money_cost:BTC:30m", reason="timeout")
        assert tripped is False
    assert cb.is_open("hfd", "smart_money_cost:BTC:30m") is False

    tripped = cb.record_failure("hfd", "smart_money_cost:BTC:30m", reason="timeout")
    assert tripped is True
    assert cb.is_open("hfd", "smart_money_cost:BTC:30m") is True


def test_recovers_after_cooldown(configured_logging):
    cb = CircuitBreaker(threshold=2, cooldown_seconds=0.1)
    cb.record_failure("hfd", "k", reason="e")
    cb.record_failure("hfd", "k", reason="e")
    assert cb.is_open("hfd", "k") is True
    time.sleep(0.15)
    assert cb.is_open("hfd", "k") is False


def test_success_resets(configured_logging):
    cb = CircuitBreaker(threshold=3, cooldown_seconds=10)
    cb.record_failure("hfd", "k", reason="e")
    cb.record_failure("hfd", "k", reason="e")
    cb.record_success("hfd", "k")
    assert cb.is_open("hfd", "k") is False
    # 需要重新累积到 threshold 才熔断
    cb.record_failure("hfd", "k", reason="e")
    cb.record_failure("hfd", "k", reason="e")
    assert cb.is_open("hfd", "k") is False


def test_snapshot_shape():
    cb = CircuitBreaker()
    cb.record_failure("hfd", "a", reason="x")
    snap = cb.snapshot()
    assert snap and snap[0]["service"] == "hfd"
    assert {"service", "key", "failures", "open"} <= set(snap[0].keys())

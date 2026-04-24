"""验证四路日志输出 + 结构化 JSON 字段。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pytest

from backend.core.config import Settings
from backend.core.logging import (
    StructuredFormatter,
    Tags,
    build_payload,
    get_sqlite_handler,
    set_sqlite_writer,
    setup_logging,
    shutdown_logging,
)


@pytest.fixture
def configured(settings: Settings):
    setup_logging(settings)
    yield settings
    shutdown_logging()


def test_structured_formatter_produces_valid_json() -> None:
    record = logging.LogRecord(
        name="collector.hfd_client",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="拉取成功",
        args=(),
        exc_info=None,
    )
    record.tags = ["HFD"]
    record.context = {"symbol": "BTC", "tf": "30m"}

    out = StructuredFormatter().format(record)
    obj = json.loads(out)

    assert obj["level"] == "INFO"
    assert obj["logger"] == "collector.hfd_client"
    assert obj["message"] == "拉取成功"
    assert obj["tags"] == ["HFD"]
    assert obj["context"]["symbol"] == "BTC"
    assert "ts" in obj


def test_build_payload_with_traceback() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys
        record = logging.LogRecord(
            name="x",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
        payload = build_payload(record)
        assert "traceback" in payload
        assert "RuntimeError: boom" in payload["traceback"]


def test_setup_logging_writes_file(configured: Settings) -> None:
    log = logging.getLogger("test.file")
    log.info("hello world", extra={"tags": [Tags.LIFECYCLE]})

    log_path = Path(configured.logging.file.path)
    if not log_path.is_absolute():
        log_path = configured.resolve_path(configured.logging.file.path)

    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "hello world" in content
    assert "test.file" in content


def test_sqlite_handler_starts_thread(configured: Settings) -> None:
    handler = get_sqlite_handler()
    assert handler is not None
    assert handler._thread is not None and handler._thread.is_alive()


def test_sqlite_handler_calls_writer(configured: Settings) -> None:
    captured: list[dict] = []

    def writer(payload: dict) -> None:
        captured.append(payload)

    set_sqlite_writer(writer)
    log = logging.getLogger("test.sqlite")

    for i in range(5):
        log.info(f"msg {i}", extra={"tags": ["TICK"], "context": {"i": i}})

    deadline = time.time() + 2.0
    while time.time() < deadline and len(captured) < 5:
        time.sleep(0.05)

    assert len(captured) >= 5
    sample = captured[0]
    assert sample["level"] == "INFO"
    assert sample["logger"] == "test.sqlite"
    assert sample["tags"] == ["TICK"]
    assert "i" in sample["context"]


def test_sqlite_handler_min_level_filters_debug(configured: Settings) -> None:
    """配置里 SQLite min_level=DEBUG（测试 fixture 改了），所以这里 DEBUG 也应到 writer。"""
    captured: list[dict] = []
    set_sqlite_writer(lambda p: captured.append(p))

    log = logging.getLogger("test.debug_pass")
    log.setLevel(logging.DEBUG)
    log.debug("debug msg")

    deadline = time.time() + 2.0
    while time.time() < deadline and not captured:
        time.sleep(0.05)

    levels = [c["level"] for c in captured]
    assert "DEBUG" in levels


def test_setup_logging_idempotent(settings: Settings) -> None:
    setup_logging(settings)
    setup_logging(settings)
    root = logging.getLogger()
    handler_types = [type(h).__name__ for h in root.handlers]
    assert handler_types.count("SQLiteQueueHandler") <= 1
    shutdown_logging()

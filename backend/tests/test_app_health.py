"""验证 FastAPI 应用能起来，/health 通。"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.core.config import get_settings, reload_settings


@pytest.fixture
def app_with_tmp_config(tmp_path: Path) -> Iterator[None]:
    src = Path(__file__).resolve().parent.parent / "config"
    dst = tmp_path / "config"
    shutil.copytree(src, dst)

    cfg_path = dst / "app.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["database"]["path"] = str(tmp_path / "data" / "mm.sqlite")
    cfg["logging"]["file"]["path"] = str(tmp_path / "logs" / "mm.log")
    cfg["logging"]["console"] = False
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    # 通过环境变量让 get_settings 找到 tmp 配置
    # 但当前实现 get_settings 用的是 DEFAULT_CONFIG_DIR，且是 lru_cache。
    # 简化处理：直接 monkey-patch DEFAULT_CONFIG_DIR
    import backend.core.config as cfg_mod

    original = cfg_mod.DEFAULT_CONFIG_DIR
    cfg_mod.DEFAULT_CONFIG_DIR = dst
    os.environ["MM_DISABLE_SCHEDULER"] = "1"
    get_settings.cache_clear()
    try:
        yield
    finally:
        cfg_mod.DEFAULT_CONFIG_DIR = original
        os.environ.pop("MM_DISABLE_SCHEDULER", None)
        get_settings.cache_clear()


def test_health_endpoint(app_with_tmp_config: None) -> None:
    from backend.main import create_app

    app = create_app()

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "MM"

        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "BTC" in body["active_symbols"]
        assert body["uptime_seconds"] >= 0
        assert body["scheduler_running"] is False  # 测试关闭

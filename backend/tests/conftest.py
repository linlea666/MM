"""测试公共 fixture。

每个测试都跑在临时目录下：
- 临时 SQLite 文件
- 临时 logs 目录
- 隔离的 Settings 实例
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from backend.core.config import Settings, load_settings
from backend.core.logging import setup_logging, shutdown_logging
from backend.storage.db import Database


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parent.parent / "config"
    dst = tmp_path / "config"
    shutil.copytree(src, dst)

    # 改写 app.yaml：DB / 日志路径全部指向 tmp_path
    app_yaml = dst / "app.yaml"
    cfg = yaml.safe_load(app_yaml.read_text(encoding="utf-8"))
    cfg["database"]["path"] = str(tmp_path / "data" / "mm.sqlite")
    cfg["logging"]["file"]["enabled"] = True
    cfg["logging"]["file"]["path"] = str(tmp_path / "logs" / "mm.log")
    cfg["logging"]["sqlite"]["enabled"] = True
    cfg["logging"]["sqlite"]["min_level"] = "DEBUG"
    cfg["logging"]["console"] = False  # 测试时少噪声
    app_yaml.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    return dst


@pytest.fixture
def settings(tmp_config_dir: Path) -> Settings:
    return load_settings(tmp_config_dir)


@pytest_asyncio.fixture
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings)
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def configured_logging(settings: Settings):
    setup_logging(settings)
    try:
        yield
    finally:
        shutdown_logging()

"""时间工具：统一用毫秒 epoch（int），ISO 字符串只在 API 边界出现。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# K 线周期 → 毫秒
TF_MS: dict[str, int] = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def iso_to_ms(iso: str) -> int:
    """支持 'YYYY-MM-DD HH:MM:SS' 和 ISO 8601 两种。"""
    iso = iso.strip().replace(" ", "T")
    if not iso.endswith("Z") and "+" not in iso[10:]:
        iso += "+00:00"
    iso = iso.replace("Z", "+00:00")
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def tf_to_ms(tf: str) -> int:
    if tf not in TF_MS:
        raise ValueError(f"unsupported timeframe: {tf}")
    return TF_MS[tf]


def floor_to_tf(ts_ms: int, tf: str) -> int:
    """将时间戳向下对齐到 K 线开盘时刻。"""
    step = tf_to_ms(tf)
    return (ts_ms // step) * step


def next_close_ms(tf: str, *, now: int | None = None) -> int:
    """返回下一根 K 线收盘的毫秒时间戳。"""
    cur = now if now is not None else now_ms()
    step = tf_to_ms(tf)
    return ((cur // step) + 1) * step


def parse_relative(spec: str) -> timedelta:
    """支持 '1h', '30m', '7d' 等。"""
    spec = spec.strip().lower()
    if spec.endswith("ms"):
        return timedelta(milliseconds=int(spec[:-2]))
    unit = spec[-1]
    value = int(spec[:-1])
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise ValueError(f"unsupported relative spec: {spec}")

"""Parsers：HFD 响应 → 原子列表。

用法：
    from backend.collector.parsers import get_parser, ParserResult

    parser = get_parser("smart_money_cost")
    result: ParserResult = parser(symbol="BTC", tf="30m", payload=hfd_json)
    # result.atoms: dict[str, list[BaseModel]]
    # result.replace_scopes: dict[str, dict]  # 价位类全量替换范围
"""

from .base import ParserFn, ParserResult
from .registry import PARSER_REGISTRY, get_parser, parse_all

__all__ = [
    "PARSER_REGISTRY",
    "ParserFn",
    "ParserResult",
    "get_parser",
    "parse_all",
]

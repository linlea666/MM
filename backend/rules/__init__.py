"""规则引擎（对应约束中的 brain 模块）。

职责：
1. 从 atoms_* 读取最近切片 → ``FeatureSnapshot``
2. 6 个纯函数 scorer：Capability -> 0-100 分 + 证据链
3. 6 个 module builder：构造 DashboardSnapshot 的各个子模块
4. ``RuleRunner``：统一编排 load → features → scores → modules → DTO

所有阈值 / 权重走 ``RulesConfigService``，代码里不出现魔法数字。
"""

from .features import FeatureExtractor, FeatureSnapshot
from .runner import NoDataError, RuleRunner

__all__ = [
    "FeatureExtractor",
    "FeatureSnapshot",
    "NoDataError",
    "RuleRunner",
]

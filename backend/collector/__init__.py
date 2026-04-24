"""采集层（对应约束中的 monitor 模块）。

职责：
1. 从 HFD 22 个 endpoint 拉原始 JSON
2. 从 Binance/OKX 拉 K 线作为真源
3. parsers 把 HFD 响应拆成原子
4. 按频率分级调度
5. 熔断 / 指数退避 / failover
6. 订阅管理（add / activate / deactivate / remove）
"""

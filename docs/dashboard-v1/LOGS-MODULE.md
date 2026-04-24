# 日志模块设计（后端结构化 + 前端可视化）

> 对标 LIQ 项目的日志面板，加强到生产级。
> 对齐开发约束 §5（日志体系）+ §6（错误处理）。

---

## 一、三层架构

```
┌────────────────────────────────────────────────────┐
│ 1. 后端：结构化日志采集                             │
│    Python logging → JSON 格式                       │
│    4 路输出：Console / File / SQLite / WebSocket   │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│ 2. API 层：查询 + 状态                              │
│    GET  /api/logs?level=&keyword=&module=&limit=   │
│    GET  /api/system/health                          │
│    WS   /ws/logs   （实时推送）                     │
└──────────────────────┬─────────────────────────────┘
                       ↓
┌────────────────────────────────────────────────────┐
│ 3. 前端：可视化日志面板（独立页面 /logs）           │
│    顶部系统状态栏 + 过滤 + 搜索 + 自动刷新          │
└────────────────────────────────────────────────────┘
```

---

## 二、后端日志实现

### 2.1 统一格式

对齐约束 §5 的文本格式：

```
[2026-04-24 03:57:45] [WARNING] rules.arbitrator: [CONFLICT] symbol=BTC 主路多 vs AI 观察空，遵循主路
```

同时对 **SQLite / WebSocket** 输出**结构化 JSON**：

```json
{
  "ts": "2026-04-24T03:57:45.123Z",
  "level": "WARNING",
  "logger": "rules.arbitrator",
  "message": "主路多 vs AI 观察空，遵循主路",
  "tags": ["CONFLICT"],
  "context": {
    "symbol": "BTC",
    "tf": "30m",
    "trace_id": "snap-20260424-035745",
    "main_conclusion": "long",
    "ai_conclusion": "short"
  },
  "traceback": null
}
```

### 2.2 Python 实现（`backend/core/logging.py`）

```python
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

class StructuredFormatter(logging.Formatter):
    """JSON 格式器，给 SQLite 和 WS 用"""
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": datetime.fromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "tags": getattr(record, "tags", []),
            "context": getattr(record, "context", {}),
        }
        if record.exc_info:
            obj["traceback"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


class SQLiteHandler(logging.Handler):
    """写入 SQLite logs 表"""
    def __init__(self, db_path: str):
        super().__init__()
        self.db_path = db_path

    def emit(self, record: logging.LogRecord):
        try:
            payload = json.loads(self.format(record))
            # 异步队列写入，避免阻塞主流程
            log_queue.put_nowait(payload)
        except Exception:
            self.handleError(record)


class WebSocketHandler(logging.Handler):
    """推送到所有 WS 订阅者"""
    def emit(self, record: logging.LogRecord):
        try:
            payload = json.loads(self.format(record))
            asyncio.create_task(ws_broadcast(payload))
        except Exception:
            self.handleError(record)


def setup_logging(config: dict):
    """应用启动时调用"""
    root = logging.getLogger()
    root.setLevel(config["level"])

    text_fmt = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    json_fmt = StructuredFormatter()

    console = logging.StreamHandler()
    console.setFormatter(text_fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        config["file_path"],
        maxBytes=config["max_size_mb"] * 1024 * 1024,
        backupCount=config["backup_count"],
        encoding="utf-8",
    )
    file_handler.setFormatter(text_fmt)
    root.addHandler(file_handler)

    sqlite_handler = SQLiteHandler(config["db_path"])
    sqlite_handler.setFormatter(json_fmt)
    sqlite_handler.setLevel(logging.INFO)  # DEBUG 不入库
    root.addHandler(sqlite_handler)

    ws_handler = WebSocketHandler()
    ws_handler.setFormatter(json_fmt)
    ws_handler.setLevel(logging.INFO)
    root.addHandler(ws_handler)
```

### 2.3 日志调用规范

每个模块用自己的 logger，统一方式附加上下文：

```python
logger = logging.getLogger("rules.arbitrator")

logger.warning(
    "主路多 vs AI 观察空，遵循主路",
    extra={
        "tags": ["CONFLICT"],
        "context": {
            "symbol": "BTC",
            "tf": "30m",
            "trace_id": trace_id,
            "main_conclusion": "long",
            "ai_conclusion": "short",
        }
    }
)
```

### 2.4 SQLite logs 表

```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    logger TEXT NOT NULL,
    message TEXT NOT NULL,
    tags TEXT,           -- JSON array
    context TEXT,        -- JSON object
    traceback TEXT
);

CREATE INDEX idx_logs_ts ON logs(ts);
CREATE INDEX idx_logs_level ON logs(level);
CREATE INDEX idx_logs_logger ON logs(logger);
```

**保留策略**：7 天自动清理（后台任务 `DELETE WHERE ts < now - 7d`）。

---

## 三、API 层

### 3.1 日志查询 `GET /api/logs`

```
参数：
  level=INFO|WARNING|ERROR|DEBUG   可多选（逗号分隔）
  module=collector|rules|ai|api    可多选
  keyword=xxx                      对 message 模糊匹配
  symbol=BTC                       从 context 过滤
  from=2026-04-24T00:00:00Z
  to=2026-04-24T23:59:59Z
  limit=300                        默认 300
  offset=0

响应：
{
  "total": 1523,
  "returned": 300,
  "logs": [
    {
      "ts": "2026-04-24T03:57:45.123Z",
      "level": "WARNING",
      "logger": "rules.arbitrator",
      "message": "...",
      "tags": ["CONFLICT"],
      "context": {...},
      "traceback": null
    },
    ...
  ]
}
```

### 3.2 系统状态 `GET /api/system/health`

```json
{
  "ts": "2026-04-24T03:58:00Z",
  "engine": {
    "status": "running",
    "uptime_seconds": 86400,
    "last_snapshot_ts": "2026-04-24T03:57:45Z"
  },
  "data_sources": {
    "hfd": {
      "status": "connected",
      "last_success_ts": "2026-04-24T03:57:40Z",
      "avg_latency_ms": 63,
      "recent_failures_1h": 0
    },
    "binance": {
      "status": "connected",
      "last_success_ts": "2026-04-24T03:57:30Z",
      "avg_latency_ms": 71,
      "recent_failures_1h": 0
    },
    "okx": {
      "status": "standby",
      "last_success_ts": null
    },
    "deepseek": {
      "status": "available",
      "last_success_ts": "2026-04-24T03:55:00Z",
      "avg_latency_ms": 2300,
      "recent_failures_1h": 0
    }
  },
  "storage": {
    "sqlite": "ok",
    "disk_free_mb": 4500,
    "db_size_mb": 128
  },
  "readiness": {
    "collection": true,
    "rules": true,
    "ai_observer": true,
    "api": true
  },
  "active_symbols": ["BTC", "ETH"],
  "timeframes": ["30m", "1h", "4h"]
}
```

### 3.3 WebSocket `/ws/logs` 实时推送

```typescript
// 前端订阅
const ws = new WebSocket("ws://host:8902/ws/logs");
ws.onmessage = (e) => {
  const log = JSON.parse(e.data);
  appendLog(log);  // 追加到列表头部
};
```

后端在每条日志 emit 时广播给所有订阅者。

### 3.4 诊断数据导出 `GET /api/logs/export`

按时间范围导出 JSON 文件，供问题分析。

---

## 四、前端日志页面 `/logs`

### 4.1 布局（对标 LIQ 截图 + 加强）

```
┌────────────────────────────────────────────────────────────────┐
│ ← 返回大屏    📊 MM 运行日志          [☑ 自动刷新]  [🔄 刷新]  │
├────────────────────────────────────────────────────────────────┤
│ 系统状态                                                        │
│ 引擎: running  │  AI: 可用 (deepseek)  │  HFD: connected(63ms) │
│ Binance: connected(71ms)  │  OKX: standby  │  SQLite: ok       │
│ 数据就绪: ✅ BTC  ✅ ETH                                         │
├────────────────────────────────────────────────────────────────┤
│ 级别: [全部] [INFO] [WARNING] [ERROR] [DEBUG]                   │
│ 模块: [全部] [collector] [rules] [ai] [api] [stats]             │
│ 币种: [全部] [BTC] [ETH]   时间: [最近1h] [24h] [7d] [自定义]   │
│ 🔍 搜索关键词...                                   300 / 1523 条│
├────────────────────────────────────────────────────────────────┤
│ 时间              级别       模块               内容            │
│ 03:57:44          INFO       api.rest           GET /api/...   │
│ 03:57:44          INFO       api.rest           ...            │
│ 03:57:45  [CONFLICT] WARNING rules.arbitrator   主路多 vs...    │
│ 03:57:47          INFO       collector.hfd      HFD fetch OK   │
│ 03:58:05  [URGENT] WARNING   rules.action_card  强信号触发...   │
│ ...                                                             │
│                                                                 │
│ [点击任一行展开 context / traceback]                            │
│                                                                 │
│                                        [↓ 滚动到最新] [📥 导出]  │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 关键功能

| 功能 | 行为 |
|------|------|
| 顶部系统状态栏 | 轮询 `/api/system/health` 每 10s 刷新；任何数据源 disconnected 变红 |
| 自动刷新 | 开启时 WS 实时推送；关闭时变成手动刷新按钮 |
| 级别多选 | [全部] 互斥，其它按钮可多选，URL 同步 `?level=WARNING,ERROR` |
| 模块过滤 | 按 `logger` 前缀过滤（如 `rules.` 前缀匹配所有规则模块）|
| 币种过滤 | 从 `context.symbol` 过滤 |
| 关键词搜索 | 防抖 300ms，空格分词 AND |
| 标签高亮 | `[URGENT]` 红色徽章 / `[AI]` 蓝色 / `[CONFLICT]` 黄色 / 自定义可扩展 |
| 级别着色 | ERROR 红 / WARNING 橙 / INFO 灰 / DEBUG 淡灰 |
| 行展开 | 点击行，下方展开 context JSON + traceback 代码块 |
| 滚动到最新 | 浮动按钮，自动刷新期间有新日志时提示"↓ X 条新日志" |
| 导出 | 调 `/api/logs/export` 下载 JSON |

### 4.3 组件结构（React）

```
frontend/src/pages/Logs/
├── index.tsx                  # 页面入口
├── SystemHealthBar.tsx        # 顶部状态栏
├── LogFilters.tsx             # 过滤 + 搜索工具栏
├── LogTable.tsx               # 日志列表（虚拟滚动）
├── LogRow.tsx                 # 单行
├── LogDetail.tsx              # 展开的 context + traceback
├── TagBadge.tsx               # 标签徽章
└── hooks/
    ├── useSystemHealth.ts     # 轮询 health
    ├── useLogs.ts             # 初始加载 + WS 订阅
    └── useLogFilters.ts       # URL state sync
```

### 4.4 虚拟滚动（性能）

用 `@tanstack/react-virtual` 做虚拟列表，300+ 条不会卡。

---

## 五、关键日志约定（每模块必打）

| 模块 | 必打日志 | Level | 标签 |
|------|---------|-------|------|
| collector.scheduler | 一轮采集开始/结束/耗时 | INFO | [TICK] |
| collector.hfd_client | endpoint 成功/失败/重试 | INFO/ERROR | [HFD] |
| collector.exchange_client | Binance 失败切 OKX | WARNING | [FAILOVER] |
| storage.atoms | 原子 upsert 冲突 | DEBUG | — |
| rules.capability.* | 能力分数计算 | DEBUG | — |
| rules.arbitrator | 冲突裁决触发 | WARNING | [CONFLICT] |
| rules.state_machine | 阶段切换 from → to | INFO | [PHASE] |
| rules.action_card | A/B/C 三情景生成 | INFO | — |
| rules.action_card | 生成高星级信号 ≥4★ | WARNING | [URGENT] |
| ai.deepseek | 请求/响应/token 数 | DEBUG | [AI] |
| ai.observer | D 情景生成 | INFO | [AI] |
| ai.observer | AI 输出缺证据被丢弃 | WARNING | [AI] |
| api.ws | 客户端连接/断开 | INFO | — |
| api.rest | 请求耗时 > 100ms | WARNING | [SLOW] |
| stats.daily_review | 日终复盘触发 | INFO | [REVIEW] |
| system | 启动 / 关闭 / 异常退出 | INFO/ERROR | [LIFECYCLE] |

---

## 六、错误处理与日志联动（约束 §6）

所有 try/except 必须：
1. 记录完整 traceback（`exc_info=True`）
2. 在 `extra.context` 里带上业务上下文（symbol、tf、trace_id、endpoint 等）
3. 对应打相应级别：
   - **可恢复** → WARNING
   - **不可恢复** → ERROR
4. 连续失败触发告警（见 Arch §6 熔断）

示例：

```python
try:
    data = await hfd.fetch(indicator, symbol, tf)
except Exception as e:
    logger.error(
        f"HFD 请求失败: {indicator}",
        extra={
            "tags": ["HFD", "FETCH_FAIL"],
            "context": {
                "indicator": indicator,
                "symbol": symbol,
                "tf": tf,
                "attempt": attempt,
                "error_type": type(e).__name__,
            }
        },
        exc_info=True,
    )
    raise
```

前端点击该 ERROR 行，自动展开完整 traceback，定位问题只需 3 秒。

---

## 七、完成度检查（约束 §10）

- [ ] (a) 正常流程：日志模块跑通 `/logs` 页面，WS 实时推送
- [ ] (b) 异常：WS 断线自动重连 + 降级到轮询
- [ ] (c) 配置化：保留天数、文件大小、过滤默认值全部在 `app.yaml`
- [ ] (d) 多币种：context.symbol 过滤验证
- [ ] (e) 定位：随便制造一个 ERROR，能在前端 3 秒定位完整 traceback

---

## 八、后续增强（V1.1+）

- 告警 webhook（连续 ERROR 触发 Telegram/Discord 推送）
- 日志聚合（按 trace_id 查看一次快照的完整日志链）
- 日志统计图表（每 5 分钟的 ERROR/WARNING 数量趋势）
- 日志中心化（若未来多实例，可接 Loki + Grafana）

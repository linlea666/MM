-- ════════════════════════════════════════════════════════════════════
-- MM SQLite Schema
-- ════════════════════════════════════════════════════════════════════
-- 字段命名与 docs/upstream-api/ATOMS.md 一一对应。
-- 时间戳全部为毫秒 epoch (INTEGER)。
-- 主键 / 索引按 ATOMS.md "去重与 Upsert 规则" 表设计。
-- ════════════════════════════════════════════════════════════════════

-- 一、元信息
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 二、订阅管理（添加即常驻，方案 B）
CREATE TABLE IF NOT EXISTS subscriptions (
    symbol         TEXT PRIMARY KEY,
    display_order  INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,    -- 1=正在采集 0=已停用
    added_at       INTEGER NOT NULL,              -- ms epoch
    last_viewed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_active
    ON subscriptions(active);

-- 三、日志（结构化）
-- 注意：logs 表已独立到 mm-logs.sqlite 文件（见 storage/schema_logs.sql），
-- 以避免高频日志写入阻塞业务事务。本文件不再包含 logs 表定义。

-- ════════════════════════════════════════════════════════════════════
-- 四、原子表（按 ATOMS.md 5 大类组织）
-- ════════════════════════════════════════════════════════════════════

-- ─── 时序点类（9 张） ───
-- 主键：(symbol, tf, ts)；upsert 最后写入覆盖。

CREATE TABLE IF NOT EXISTS atoms_klines (
    symbol  TEXT NOT NULL,
    tf      TEXT NOT NULL,
    ts      INTEGER NOT NULL,
    open    REAL NOT NULL,
    high    REAL NOT NULL,
    low     REAL NOT NULL,
    close   REAL NOT NULL,
    volume  REAL NOT NULL,
    source  TEXT NOT NULL DEFAULT 'binance',
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_cvd (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    value  REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_imbalance (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    value  REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_inst_vol (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    value  REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_vwap (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    vwap   REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_poc_shift (
    symbol    TEXT NOT NULL,
    tf        TEXT NOT NULL,
    ts        INTEGER NOT NULL,
    poc_price REAL NOT NULL,
    volume    REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_trailing_vwap (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    resistance REAL,
    support    REAL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_power_imbalance (
    symbol   TEXT NOT NULL,
    tf       TEXT NOT NULL,
    ts       INTEGER NOT NULL,
    buy_vol  REAL NOT NULL,
    sell_vol REAL NOT NULL,
    ratio    REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS atoms_trend_exhaustion (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    exhaustion INTEGER NOT NULL,
    type       TEXT NOT NULL,                  -- Accumulation/Distribution
    PRIMARY KEY (symbol, tf, ts)
);

-- ─── 段式区间类（5 张） ───
-- 主键：(symbol, tf, start_time, type)

CREATE TABLE IF NOT EXISTS atoms_smart_money (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time   INTEGER NOT NULL,
    avg_price  REAL NOT NULL,
    type       TEXT NOT NULL,
    status     TEXT NOT NULL,                  -- Ongoing/Completed
    PRIMARY KEY (symbol, tf, start_time, type)
);

CREATE TABLE IF NOT EXISTS atoms_order_blocks (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    avg_price  REAL NOT NULL,
    volume     REAL NOT NULL,
    type       TEXT NOT NULL,
    PRIMARY KEY (symbol, tf, start_time, type)
);

CREATE TABLE IF NOT EXISTS atoms_absolute_zones (
    symbol       TEXT NOT NULL,
    tf           TEXT NOT NULL,
    start_time   INTEGER NOT NULL,
    bottom_price REAL NOT NULL,
    top_price    REAL NOT NULL,
    type         TEXT NOT NULL,
    PRIMARY KEY (symbol, tf, start_time, type)
);

CREATE TABLE IF NOT EXISTS atoms_micro_poc (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time   INTEGER,
    poc_price  REAL NOT NULL,
    volume     REAL NOT NULL,
    type       TEXT NOT NULL,
    PRIMARY KEY (symbol, tf, start_time, type)
);

CREATE TABLE IF NOT EXISTS atoms_trend_purity (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    end_time   INTEGER,
    avg_price  REAL NOT NULL,
    buy_vol    REAL NOT NULL,
    sell_vol   REAL NOT NULL,
    total_vol  REAL NOT NULL,
    purity     REAL NOT NULL,
    type       TEXT NOT NULL,
    PRIMARY KEY (symbol, tf, start_time, type)
);

-- ─── 事件类（2 张） ───
-- 主键：(symbol, tf, ts, price, type)

CREATE TABLE IF NOT EXISTS atoms_resonance_events (
    symbol    TEXT NOT NULL,
    tf        TEXT NOT NULL,
    ts        INTEGER NOT NULL,
    price     REAL NOT NULL,
    direction TEXT NOT NULL,                   -- buy/sell
    count     INTEGER NOT NULL,
    exchanges TEXT NOT NULL,                   -- JSON array
    PRIMARY KEY (symbol, tf, ts, price, direction)
);

CREATE TABLE IF NOT EXISTS atoms_sweep_events (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    ts     INTEGER NOT NULL,
    price  REAL NOT NULL,
    type   TEXT NOT NULL,                      -- bullish_sweep/bearish_sweep
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, tf, ts, price, type)
);

-- ─── 价位类（5 张） ───
-- heatmap：(symbol, tf, start_time, price, type)
-- vacuum/fuel/hvn/volume_profile：每次拉取全量覆盖（DELETE+INSERT 在 repository 实现）

CREATE TABLE IF NOT EXISTS atoms_heatmap (
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    start_time INTEGER NOT NULL,
    price      REAL NOT NULL,
    intensity  REAL NOT NULL,
    type       TEXT NOT NULL,
    PRIMARY KEY (symbol, tf, start_time, price, type)
);

CREATE TABLE IF NOT EXISTS atoms_vacuum (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    low    REAL NOT NULL,
    high   REAL NOT NULL,
    PRIMARY KEY (symbol, tf, low, high)
);

CREATE TABLE IF NOT EXISTS atoms_liquidation_fuel (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    bottom REAL NOT NULL,
    top    REAL NOT NULL,
    fuel   REAL NOT NULL,
    PRIMARY KEY (symbol, tf, bottom, top)
);

CREATE TABLE IF NOT EXISTS atoms_hvn_nodes (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    rank   INTEGER NOT NULL,
    price  REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, tf, rank)
);

CREATE TABLE IF NOT EXISTS atoms_volume_profile (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    price  REAL NOT NULL,
    accum  REAL NOT NULL,
    dist   REAL NOT NULL,
    total  REAL NOT NULL,
    PRIMARY KEY (symbol, tf, price)
);

-- ─── 聚合统计类（2 张） ───

CREATE TABLE IF NOT EXISTS atoms_time_heatmap (
    symbol TEXT NOT NULL,
    tf     TEXT NOT NULL,
    hour   INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    accum  REAL NOT NULL,
    dist   REAL NOT NULL,
    total  REAL NOT NULL,
    PRIMARY KEY (symbol, tf, hour)
);

CREATE TABLE IF NOT EXISTS atoms_trend_saturation (
    symbol      TEXT NOT NULL,
    tf          TEXT NOT NULL,
    type        TEXT NOT NULL,
    start_time  INTEGER NOT NULL,
    avg_vol     REAL NOT NULL,
    current_vol REAL NOT NULL,
    progress    REAL NOT NULL,
    PRIMARY KEY (symbol, tf)
);

-- ════════════════════════════════════════════════════════════════════
-- 五、配置覆盖（前端可调阈值）
-- ════════════════════════════════════════════════════════════════════
-- 运行时 = rules.default.yaml  DEEP MERGE  config_overrides
-- YAML 永远是“出厂默认 + Git 可审查”，SQLite 只存前端/AI 改过的差异。

CREATE TABLE IF NOT EXISTS config_overrides (
    key         TEXT PRIMARY KEY,              -- 如 rules.accumulation.weights.whale_resonance
    value       TEXT NOT NULL,                 -- JSON 编码
    value_type  TEXT NOT NULL,                 -- number/int/bool/string/array/object
    updated_at  INTEGER NOT NULL,
    updated_by  TEXT NOT NULL,                 -- user / ai_review / system
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS config_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,                          -- NULL 表示 reset
    updated_at  INTEGER NOT NULL,
    updated_by  TEXT NOT NULL,
    reason      TEXT
);

CREATE INDEX IF NOT EXISTS idx_config_audit_key_ts
    ON config_audit(key, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_config_audit_ts
    ON config_audit(updated_at DESC);

-- ════════════════════════════════════════════════════════════════════
-- 六、快照（V1 输出，可选缓存）
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS dashboard_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT NOT NULL,
    tf         TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    payload    TEXT NOT NULL                   -- JSON
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_tf_ts
    ON dashboard_snapshots(symbol, tf, ts DESC);

-- ════════════════════════════════════════════════════════════════════
-- 七、完成度自检
-- ════════════════════════════════════════════════════════════════════

INSERT OR REPLACE INTO schema_meta(key, value)
    VALUES ('schema_version', '2');

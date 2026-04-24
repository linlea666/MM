-- ════════════════════════════════════════════════════════════════════
-- MM 日志库 schema（独立 SQLite 文件）
-- ════════════════════════════════════════════════════════════════════
-- 物理上与业务库 mm.sqlite 分离，避免日志高频写入阻塞业务事务。
-- 文件路径由 settings.database.logs_path 控制（默认 logs/mm-logs.sqlite）。

CREATE TABLE IF NOT EXISTS logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,                      -- ISO 8601
    level     TEXT NOT NULL,                      -- DEBUG/INFO/WARNING/ERROR
    logger    TEXT NOT NULL,                      -- 模块路径
    message   TEXT NOT NULL,
    tags      TEXT,                               -- JSON array
    context   TEXT,                               -- JSON object
    traceback TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_ts     ON logs(ts);
CREATE INDEX IF NOT EXISTS idx_logs_level  ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_logger ON logs(logger);

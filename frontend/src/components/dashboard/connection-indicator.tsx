import { useEffect, useState } from "react";
import { Radio, RefreshCw, WifiOff } from "lucide-react";

import type { WsStatus } from "@/lib/ws";
import { cn } from "@/lib/utils";

interface Props {
  wsStatus: WsStatus;
  wsLive: boolean;
  lastSnapshotAt: number | null;
  source: "ws" | "rest" | null;
  onRefresh?: () => void;
}

export function ConnectionIndicator({
  wsStatus,
  wsLive,
  lastSnapshotAt,
  source,
  onRefresh,
}: Props) {
  // 每秒重渲染一次以更新"xx 秒前"
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setTick((n) => n + 1), 1_000);
    return () => window.clearInterval(t);
  }, []);

  const ago = lastSnapshotAt
    ? Math.max(0, Math.round((Date.now() - lastSnapshotAt) / 1000))
    : null;

  let mode: "live" | "connecting" | "polling" | "offline" = "offline";
  if (wsLive && wsStatus === "open") mode = "live";
  else if (wsStatus === "connecting") mode = "connecting";
  else if (wsStatus === "open" && !wsLive) mode = "connecting";
  else mode = "polling";

  const color =
    mode === "live"
      ? "text-bullish"
      : mode === "connecting"
        ? "text-warning"
        : mode === "polling"
          ? "text-muted-foreground"
          : "text-destructive";

  const dotColor =
    mode === "live"
      ? "bg-bullish"
      : mode === "connecting"
        ? "bg-warning"
        : mode === "polling"
          ? "bg-muted-foreground"
          : "bg-destructive";

  const label =
    mode === "live"
      ? "实时推送"
      : mode === "connecting"
        ? "连接中…"
        : mode === "polling"
          ? "WS 离线 · 5s 轮询兜底"
          : "离线";

  return (
    <div className="flex items-center justify-end gap-3 text-xs text-muted-foreground">
      <div className="flex items-center gap-1.5">
        <span className={cn("relative flex h-2 w-2")}>
          {mode === "live" && (
            <span
              className={cn(
                "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
                dotColor,
              )}
            />
          )}
          <span
            className={cn(
              "relative inline-flex h-2 w-2 rounded-full",
              dotColor,
            )}
          />
        </span>
        <span className={cn("font-medium", color)}>
          {mode === "live" ? <Radio className="inline h-3 w-3" /> : null}
          {mode === "polling" ? <WifiOff className="inline h-3 w-3" /> : null} {label}
        </span>
      </div>

      {ago !== null && (
        <span>
          最后一帧 <span className="font-mono num">{ago}</span>s 前
          {source === "ws" ? " · ws" : source === "rest" ? " · rest" : ""}
        </span>
      )}

      {onRefresh && (
        <button
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-accent/40 hover:text-foreground"
          onClick={onRefresh}
          title="手动拉取一次 REST"
        >
          <RefreshCw className="h-3 w-3" />
          手动刷新
        </button>
      )}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, Trash2, Wifi, WifiOff } from "lucide-react";

import { WsClient, type WsStatus } from "@/lib/ws";
import type { LogEntry, WsLogMsg } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";

import type { LogFilter } from "./log-filter-bar";
import { LogRow } from "./log-row";

interface Props {
  filter: LogFilter;
  /** 环形缓存上限 */
  maxBuffer?: number;
}

export function LogLiveTail({ filter, maxBuffer = 500 }: Props) {
  const [paused, setPaused] = useState(false);
  const [status, setStatus] = useState<WsStatus>("closed");
  const [buffer, setBuffer] = useState<LogEntry[]>([]);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  // 订阅帧签名（levels / loggers 任一改变就 resend）
  const subscribeFrame = useMemo(
    () => ({
      action: "subscribe",
      levels: filter.levels,
      loggers: filter.loggers,
    }),
    [filter.levels, filter.loggers],
  );

  const clientRef = useRef<WsClient<WsLogMsg> | null>(null);

  // 建立 WS
  useEffect(() => {
    const client = new WsClient<WsLogMsg>({
      path: "/ws/logs",
      subscribeFrame,
      onStatus: setStatus,
      onMessage: (msg) => {
        if (msg.type !== "log") return;
        if (pausedRef.current) return;
        setBuffer((buf) => {
          const next = [msg.data, ...buf];
          return next.length > maxBuffer ? next.slice(0, maxBuffer) : next;
        });
      },
    });
    clientRef.current = client;
    client.connect();
    return () => {
      client.close();
      clientRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 过滤器变化 → 重新订阅
  useEffect(() => {
    clientRef.current?.setSubscribeFrame(subscribeFrame);
  }, [subscribeFrame]);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">
          实时尾部
          <StatusBadge status={status} />
        </CardTitle>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setPaused((v) => !v)}
          >
            {paused ? (
              <>
                <Play className="mr-1 h-3.5 w-3.5" />
                继续
              </>
            ) : (
              <>
                <Pause className="mr-1 h-3.5 w-3.5" />
                暂停
              </>
            )}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setBuffer([])}
            disabled={buffer.length === 0}
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            清空
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>
            缓存 <span className="font-mono num text-foreground/80">{buffer.length}</span> /{" "}
            {maxBuffer} 条
          </span>
          {paused && (
            <span className="rounded bg-warning/20 px-1.5 py-0.5 text-[10px] font-medium text-warning">
              已暂停，不再接收
            </span>
          )}
          {(filter.levels.length > 0 || filter.loggers.length > 0) && (
            <span className="text-[10px] italic">
              订阅过滤：
              {filter.levels.length > 0 && `levels=${filter.levels.join(",")} `}
              {filter.loggers.length > 0 && `loggers=${filter.loggers.join(",")}`}
            </span>
          )}
        </div>

        {(() => {
          const visible = buffer.filter((row) =>
            matchLocal(row, filter.keyword, filter.symbol),
          );
          if (buffer.length === 0) {
            return (
              <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border/40 py-10 text-sm text-muted-foreground">
                <WifiOff className="h-5 w-5 opacity-60" />
                {status === "open"
                  ? "已连接，等待后端产生新日志…"
                  : status === "connecting"
                    ? "连接中…"
                    : "等待连接"}
              </div>
            );
          }
          return (
            <ScrollArea className="h-[480px] pr-2">
              <div className="flex flex-col gap-1.5">
                {visible.length === 0 ? (
                  <div className="py-6 text-center text-xs text-muted-foreground">
                    缓存中无匹配关键词/币种的日志
                  </div>
                ) : (
                  visible.map((row, i) => (
                    <LogRow key={row.id ?? `${row.ts}-${i}`} row={row} />
                  ))
                )}
              </div>
            </ScrollArea>
          );
        })()}
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: WsStatus }) {
  const ok = status === "open";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium",
        ok
          ? "bg-bullish/20 text-bullish"
          : status === "connecting"
            ? "bg-warning/20 text-warning"
            : "bg-muted text-muted-foreground",
      )}
    >
      {ok ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
      {status}
    </span>
  );
}

/** WS 侧只按 levels / loggers 订阅；keyword / symbol 在客户端侧过滤显示。 */
function matchLocal(row: LogEntry, keyword: string, symbol: string): boolean {
  if (keyword) {
    const k = keyword.toLowerCase();
    if (!row.message.toLowerCase().includes(k)) return false;
  }
  if (symbol) {
    const s = symbol.toUpperCase();
    const ctx = row.context as Record<string, unknown> | undefined;
    const ctxSym = String(ctx?.symbol ?? "").toUpperCase();
    if (!ctxSym.includes(s) && !row.message.toUpperCase().includes(s)) {
      return false;
    }
  }
  return true;
}

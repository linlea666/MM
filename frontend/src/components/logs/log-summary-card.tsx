import { useQuery } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

import { fetchLogsSummary } from "@/lib/api";
import type { LogLevel, LogsSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { levelColor } from "@/lib/logs-helpers";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const LEVELS: LogLevel[] = ["ERROR", "WARNING", "INFO", "DEBUG"];

export function LogSummaryCard() {
  const q = useQuery<LogsSummary>({
    queryKey: ["logs-summary"],
    queryFn: fetchLogsSummary,
    refetchInterval: 30_000,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>日志概览</CardTitle>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => q.refetch()}
          disabled={q.isFetching}
        >
          <RotateCw
            className={cn(
              "mr-1 h-3.5 w-3.5",
              q.isFetching && "animate-spin",
            )}
          />
          刷新
        </Button>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : q.isError ? (
          <div className="text-sm text-muted-foreground">概览加载失败</div>
        ) : q.data ? (
          <div className="grid gap-4 md:grid-cols-3">
            {/* 近 1h */}
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">近 1 小时</div>
              <LevelGrid counts={q.data.last_1h} />
            </div>
            {/* 近 24h */}
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">
                近 24 小时 · 累计 {q.data.total}
              </div>
              <LevelGrid counts={q.data.last_24h} />
            </div>
            {/* Top loggers */}
            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">Top loggers · 24h</div>
              <div className="space-y-1">
                {q.data.top_loggers_24h.slice(0, 5).map((row) => (
                  <div
                    key={row.logger}
                    className="flex items-center justify-between gap-2 rounded border border-border/30 bg-background/40 px-2 py-1 text-xs"
                  >
                    <span className="truncate font-mono text-foreground/80">
                      {row.logger}
                    </span>
                    <span className="shrink-0 font-mono num text-muted-foreground">
                      {row.count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function LevelGrid({ counts }: { counts: Record<LogLevel, number> }) {
  return (
    <div className="grid grid-cols-4 gap-1.5">
      {LEVELS.map((lv) => (
        <div
          key={lv}
          className={cn(
            "rounded-md border border-border/40 px-2 py-1.5 text-center",
            (counts[lv] ?? 0) > 0 && lv === "ERROR" && "ring-1 ring-destructive/40",
          )}
        >
          <div
            className={cn(
              "inline-block rounded px-1 text-[10px] font-medium",
              levelColor(lv),
            )}
          >
            {lv}
          </div>
          <div className="mt-1 font-mono num text-lg font-semibold">
            {counts[lv] ?? 0}
          </div>
        </div>
      ))}
    </div>
  );
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Inbox } from "lucide-react";

import { queryLogs } from "@/lib/api";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";

import {
  isFilterEmpty,
  type LogFilter,
  toIsoIfAny,
} from "./log-filter-bar";
import { LogRow } from "./log-row";

interface Props {
  filter: LogFilter;
}

export function LogQueryTable({ filter }: Props) {
  const [offset, setOffset] = useState(0);

  // filter 变化后回到首页
  const filterSig = JSON.stringify({ ...filter, _offset: undefined });
  const [lastSig, setLastSig] = useState(filterSig);
  if (lastSig !== filterSig) {
    setLastSig(filterSig);
    setOffset(0);
  }

  const q = useQuery({
    queryKey: ["logs", filterSig, offset],
    queryFn: () =>
      queryLogs({
        levels: filter.levels.length ? filter.levels : undefined,
        loggers: filter.loggers.length ? filter.loggers : undefined,
        keyword: filter.keyword || undefined,
        symbol: filter.symbol || undefined,
        from_ts: toIsoIfAny(filter.from_ts),
        to_ts: toIsoIfAny(filter.to_ts),
        limit: filter.limit,
        offset,
      }),
    refetchInterval: isFilterEmpty(filter) ? 8_000 : false,
    placeholderData: (prev) => prev,
  });

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        {q.isLoading && !q.data ? (
          <Skeleton className="h-96 w-full" />
        ) : q.isError ? (
          <div className="p-6 text-center text-sm text-destructive">
            查询失败：
            {(q.error as Error & { friendly?: string })?.friendly}
          </div>
        ) : (q.data?.items.length ?? 0) === 0 ? (
          <div className="flex flex-col items-center gap-2 p-10 text-sm text-muted-foreground">
            <Inbox className="h-6 w-6" />
            没有匹配的日志
          </div>
        ) : (
          <ScrollArea className="h-[540px] pr-2">
            <div className="flex flex-col gap-1.5">
              {(q.data?.items ?? []).map((row, i) => (
                <LogRow key={row.id ?? `${row.ts}-${i}`} row={row} />
              ))}
            </div>
          </ScrollArea>
        )}

        {/* 分页 */}
        <div className="flex items-center justify-between gap-2 border-t border-border/40 pt-2 text-xs text-muted-foreground">
          <div>
            共 {q.data?.count ?? 0} 条 · offset={offset}
            {q.isFetching && " · 加载中…"}
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setOffset((o) => Math.max(0, o - (filter.limit ?? 200)))
              }
              disabled={offset === 0 || q.isFetching}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              上一页
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (q.data?.next_offset !== null && q.data?.next_offset !== undefined) {
                  setOffset(q.data.next_offset);
                }
              }}
              disabled={!q.data?.has_more || q.isFetching}
            >
              下一页
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

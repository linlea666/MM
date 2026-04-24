import { useQuery } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";

import { fetchConfigAudit } from "@/lib/api";
import { formatConfigValue } from "@/lib/config-utils";
import { cn, formatDateTime } from "@/lib/utils";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  keyFilter?: string;
}

export function AuditPanel({ keyFilter }: Props) {
  const q = useQuery({
    queryKey: ["config-audit", keyFilter ?? ""],
    queryFn: () =>
      fetchConfigAudit({
        key: keyFilter,
        limit: 200,
      }),
    refetchInterval: 20_000,
  });

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">
          审计历史
          {keyFilter && (
            <span className="font-mono text-xs text-muted-foreground">
              · {keyFilter}
            </span>
          )}
        </CardTitle>
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
      <CardContent className="p-0">
        {q.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : q.isError ? (
          <div className="p-6 text-center text-sm text-muted-foreground">
            加载失败
          </div>
        ) : (q.data?.items.length ?? 0) === 0 ? (
          <div className="p-6 text-center text-sm text-muted-foreground">
            暂无审计记录
          </div>
        ) : (
          <ScrollArea className="h-[420px]">
            <table className="w-full text-sm">
              <thead className="sticky top-0 border-b border-border/40 bg-background/90 text-xs text-muted-foreground backdrop-blur">
                <tr className="text-left">
                  <th className="px-3 py-2 font-medium">时间</th>
                  <th className="px-3 py-2 font-medium">操作人</th>
                  <th className="px-3 py-2 font-medium">配置项</th>
                  <th className="px-3 py-2 font-medium">旧值 → 新值</th>
                  <th className="px-3 py-2 font-medium">说明</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {(q.data?.items ?? []).map((r) => (
                  <tr key={r.id} className="hover:bg-accent/30">
                    <td className="px-3 py-2 font-mono num text-xs text-muted-foreground">
                      {formatDateTime(r.updated_at)}
                    </td>
                    <td className="px-3 py-2">
                      <span className="rounded bg-secondary/60 px-1.5 py-0.5 text-xs">
                        {r.updated_by}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-foreground/90">
                      {r.key}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5 font-mono num text-xs">
                        <span className="text-muted-foreground line-through">
                          {formatConfigValue(r.old_value)}
                        </span>
                        <span className="text-muted-foreground">→</span>
                        <span
                          className={cn(
                            r.new_value === null
                              ? "italic text-warning"
                              : "text-bullish",
                          )}
                        >
                          {r.new_value === null
                            ? "(重置为默认)"
                            : formatConfigValue(r.new_value)}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {r.reason ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

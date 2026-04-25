/**
 * 大屏右下「最近 N 条深度分析报告」卡片。
 *
 * - 拉 ``/api/ai/reports?limit=10``；
 * - 每行一句话摘要 + 时间 + 状态徽标；
 * - 整行点击跳详情页 ``/analysis/{id}``；
 * - 标题右上角"全部"链接跳列表页。
 *
 * 设计：默认折叠成 2 行；点击展开看完整 10 条。
 *      列表为空时提示"还没生成过深度分析"，附按钮跳分析页。
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Loader2,
} from "lucide-react";
import { fetchAIReports, type AIReportsListItem } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function fmtAge(ms: number): string {
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 60) return `${sec}s 前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

function ReportLine({ item }: { item: AIReportsListItem }) {
  const isErr = item.status === "error";
  return (
    <Link
      to={`/analysis/${item.id}`}
      className={cn(
        "flex items-start gap-3 rounded-md border border-border/30 bg-card/30 px-3 py-2 transition-colors",
        "hover:border-primary/40 hover:bg-card/60",
      )}
    >
      <div className="flex flex-col items-center gap-0.5 min-w-[64px]">
        <span className="text-[10px] text-muted-foreground">{fmtAge(item.ts)}</span>
        <Badge
          variant={isErr ? "destructive" : "outline"}
          className="text-[9px] px-1 py-0"
        >
          {isErr ? "失败" : "OK"}
        </Badge>
      </div>
      <div className="flex-1 min-w-0">
        <div
          className={cn(
            "text-xs leading-snug line-clamp-2",
            isErr ? "text-destructive/90" : "text-foreground/85",
          )}
        >
          {item.one_line || (isErr ? "深度分析失败，点击查看 raw_payloads" : "（无摘要）")}
        </div>
        <div className="mt-0.5 text-[10px] text-muted-foreground/70 truncate">
          {item.symbol} · {item.tf} · {item.model_tier} ·{" "}
          {item.total_tokens.toLocaleString()} tok
        </div>
      </div>
    </Link>
  );
}

export function RecentReportsCard() {
  const [expanded, setExpanded] = useState(false);
  const q = useQuery({
    queryKey: ["ai-reports", 10],
    queryFn: () => fetchAIReports(10),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const items = q.data?.items ?? [];
  const visible = expanded ? items : items.slice(0, 2);

  return (
    <div className="panel-glass rounded-lg">
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Brain className="size-4 text-primary" />
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              AI 深度分析
            </div>
            <div className="mt-0.5 text-sm font-semibold">
              最近报告 <span className="text-muted-foreground">({items.length})</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/analysis"
            className="inline-flex items-center gap-1 rounded-md border border-border/40 bg-background/40 px-2 py-1 text-xs text-muted-foreground hover:bg-background hover:text-foreground transition-colors"
          >
            全部 <ExternalLink className="size-3" />
          </Link>
          {items.length > 2 && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="rounded-md border border-border/40 bg-background/40 p-1 text-muted-foreground hover:bg-background hover:text-foreground transition-colors"
              title={expanded ? "折叠" : "展开"}
            >
              {expanded ? (
                <ChevronUp className="size-3.5" />
              ) : (
                <ChevronDown className="size-3.5" />
              )}
            </button>
          )}
        </div>
      </div>
      <div className="border-t border-border/30 p-3 space-y-2">
        {q.isLoading && (
          <div className="flex items-center justify-center gap-2 py-4 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            加载中…
          </div>
        )}

        {!q.isLoading && items.length === 0 && (
          <div className="text-center py-4 text-xs text-muted-foreground">
            <div>还没生成过深度分析报告。</div>
            <Link
              to="/analysis"
              className="mt-2 inline-flex items-center gap-1 text-primary hover:underline"
            >
              去生成第一份
              <ExternalLink className="size-3" />
            </Link>
          </div>
        )}

        {visible.map((it) => (
          <ReportLine key={it.id} item={it} />
        ))}
      </div>
    </div>
  );
}

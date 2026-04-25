/**
 * AI 深度分析 · 列表 + 一键分析。
 *
 * 结构（自上而下）：
 *  - Header（标题 + 「立即分析」按钮 + 当前 symbol/tf）
 *  - 历史报告列表（最近 N 条，点击进详情）
 *
 * 分析点击流程：
 *  1. 立即在列表顶部展示 "loading row"（防止用户怀疑卡死）；
 *  2. 后端最长 ~3 分钟（pro+thinking 兜底），axios timeout 已抬到 180s；
 *  3. 成功 → react-query invalidate 列表 + push 跳详情；
 *  4. 失败 → 顶部红条 + 不跳转。
 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Brain,
  ChevronRight,
  Loader2,
  RefreshCw,
} from "lucide-react";
import {
  fetchAIReports,
  runAIAnalyze,
  type AIReportsListItem,
} from "@/lib/api";
import { useSymbolStore } from "@/stores/symbol-store";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function fmtTs(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function fmtAge(ms: number): string {
  const sec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (sec < 60) return `${sec}s 前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
}

function ReportRow({ item }: { item: AIReportsListItem }) {
  const isErr = item.status === "error";
  return (
    <Link
      to={`/analysis/${item.id}`}
      className={cn(
        "group flex items-stretch gap-4 rounded-lg border border-border/50 bg-card/50 p-4 transition-all",
        "hover:border-primary/40 hover:bg-card/80",
      )}
    >
      <div className="flex flex-col items-center justify-center gap-1 min-w-[88px]">
        <div className="text-xs text-muted-foreground">{fmtAge(item.ts)}</div>
        <Badge variant={isErr ? "destructive" : "outline"} className="text-[10px]">
          {isErr ? "失败" : "成功"}
        </Badge>
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{item.symbol}</span>
          <span>·</span>
          <span>{item.tf}</span>
          <span>·</span>
          <span className="uppercase">{item.model_tier}</span>
          {item.thinking_enabled && (
            <Badge variant="secondary" className="text-[9px] px-1 py-0">
              thinking
            </Badge>
          )}
          <span>·</span>
          <span>{item.total_tokens.toLocaleString()} tok</span>
          <span>·</span>
          <span>{(item.total_latency_ms / 1000).toFixed(1)}s</span>
        </div>
        <div
          className={cn(
            "text-sm leading-relaxed line-clamp-2",
            isErr ? "text-destructive" : "text-foreground",
          )}
        >
          {item.one_line || (isErr ? "AI 综合分析失败，点击查看 raw_payloads" : "（无摘要）")}
        </div>
        <div className="text-[11px] text-muted-foreground/70 truncate">
          {fmtTs(item.ts)} · id={item.id}
        </div>
      </div>
      <div className="flex items-center text-muted-foreground group-hover:text-primary">
        <ChevronRight className="size-5" />
      </div>
    </Link>
  );
}

export default function AnalysisPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const symbol = useSymbolStore((s) => s.symbol);
  const tf = useSymbolStore((s) => s.tf);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const reports = useQuery({
    queryKey: ["ai-reports", 30],
    queryFn: () => fetchAIReports(30),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => runAIAnalyze({ symbol, tf }),
    onSuccess: (report) => {
      setErrorMsg(null);
      qc.invalidateQueries({ queryKey: ["ai-reports"] });
      navigate(`/analysis/${report.id}`);
    },
    onError: (err: Error & { friendly?: string }) => {
      setErrorMsg(err.friendly ?? err.message ?? "分析失败");
    },
  });

  const items = reports.data?.items ?? [];

  return (
    <div className="container mx-auto p-4 max-w-5xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Brain className="size-6 text-primary" />
            AI 深度分析
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            综合 4 层 LLM 推理（趋势 · 资金面 · 计划 · 综合研报），含原始交互数据，可跨模型对照。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => reports.refetch()}
            className="rounded-md border border-border/50 bg-background/50 p-2 hover:bg-background"
            title="刷新列表"
          >
            <RefreshCw
              className={cn(
                "size-4 text-muted-foreground",
                reports.isFetching && "animate-spin",
              )}
            />
          </button>
          <button
            type="button"
            disabled={analyzeMutation.isPending}
            onClick={() => analyzeMutation.mutate()}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-60 disabled:cursor-not-allowed",
            )}
          >
            {analyzeMutation.isPending ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                分析中…
              </>
            ) : (
              <>
                <Brain className="size-4" />
                立即分析 {symbol}/{tf}
              </>
            )}
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="size-4 mt-0.5 flex-shrink-0" />
          <div className="flex-1">
            <div className="font-medium">分析失败</div>
            <div className="mt-1 text-xs opacity-80">{errorMsg}</div>
          </div>
        </div>
      )}

      {analyzeMutation.isPending && (
        <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin text-primary" />
            <span className="font-medium text-foreground">
              正在跑 4 层 LLM 推理…
            </span>
          </div>
          <div className="mt-1 text-xs opacity-80">
            预计耗时 30 秒～3 分钟（取决于模型/思维模式）。完成后将自动跳转到详情页。
          </div>
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            历史报告 <span className="text-foreground">({items.length})</span>
          </span>
          {reports.data && (
            <span className="text-xs">
              ring 容量 {reports.data.size} · 上限 {reports.data.limit}
            </span>
          )}
        </div>

        {reports.isLoading && (
          <div className="rounded-lg border border-border/50 bg-card/30 p-8 text-center text-sm text-muted-foreground">
            <Loader2 className="size-5 mx-auto animate-spin mb-2" />
            加载中…
          </div>
        )}

        {!reports.isLoading && items.length === 0 && (
          <div className="rounded-lg border border-dashed border-border/50 p-8 text-center text-sm text-muted-foreground">
            还没有任何报告。点击右上角「立即分析」生成第一份。
          </div>
        )}

        {items.map((it) => (
          <ReportRow key={it.id} item={it} />
        ))}
      </div>
    </div>
  );
}

/**
 * AI 深度分析 · 单条详情。
 *
 * 顶部：摘要 hero（一句话 / 状态 / token / latency / 模型）。
 * 中部：完整 Markdown 报告（report_md，对应 L4 输出）。
 * 底部："AI 交互过程原文"区块（图 5 风格）：每层一个可展开抽屉，
 *      展示 system_prompt / user_prompt / raw_response 三段，
 *      额外加一个"跨模型对照数据切片"卡（data_slice，已剥规则/指令）。
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Cpu,
  FileText,
  Loader2,
  MessageSquare,
  Scale,
} from "lucide-react";
import { fetchAIReport, type AIRawPayload } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { MarkdownLite } from "@/components/analysis/markdown-lite";

function fmtTs(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border/50 bg-background/50 px-2 py-1 text-xs transition-colors",
        "hover:bg-background hover:text-foreground",
        copied && "border-emerald-500/40 text-emerald-500",
      )}
      title="复制内容"
    >
      {copied ? (
        <>
          <Check className="size-3" /> 已复制
        </>
      ) : (
        <>
          <Copy className="size-3" /> 复制
        </>
      )}
    </button>
  );
}

interface RawPayloadRowProps {
  title: string;
  hint: string;
  Icon: React.ComponentType<{ className?: string }>;
  text: string;
}

function RawPayloadRow({ title, hint, Icon, text }: RawPayloadRowProps) {
  const [open, setOpen] = useState(false);
  const len = text.length;
  return (
    <div className="rounded-lg border border-border/50 bg-card/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 p-3 text-left hover:bg-card/60 transition-colors"
      >
        <Icon className="size-5 text-primary flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm">{title}</div>
          <div className="text-xs text-muted-foreground line-clamp-1">{hint}</div>
        </div>
        <Badge variant="outline" className="font-mono text-[10px]">
          {len.toLocaleString()} chars
        </Badge>
        {open ? (
          <ChevronDown className="size-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 text-muted-foreground" />
        )}
      </button>
      {open && (
        <div className="border-t border-border/40 p-3 space-y-2">
          <div className="flex items-center justify-end">
            <CopyButton text={text} />
          </div>
          <pre className="overflow-x-auto rounded-md border border-border/30 bg-muted/30 p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-h-[60vh]">
            {text || "（空）"}
          </pre>
        </div>
      )}
    </div>
  );
}

const LAYER_META: Record<
  string,
  { title: string; hint: string }
> = {
  trend: {
    title: "L1 · TrendClassifier",
    hint: "趋势方向 / 阶段 / 强度 / 置信度",
  },
  money_flow: {
    title: "L2 · MoneyFlowReader",
    hint: "主力动向 / 关键磁吸带 / 资金面叙事",
  },
  trade_plan: {
    title: "L3 · TradePlanner",
    hint: "交易计划草案 / 触发条件 / R:R / 风险旗标",
  },
  deep_analyze: {
    title: "L4 · DeepAnalyzer",
    hint: "综合研报 markdown 原文 / 多场景预演 / 复盘建议",
  },
};

export default function AnalysisReportPage() {
  const { reportId } = useParams<{ reportId: string }>();

  const q = useQuery({
    queryKey: ["ai-report", reportId],
    queryFn: () => fetchAIReport(reportId!),
    enabled: !!reportId,
    staleTime: Infinity, // 报告一旦生成就不会变
    retry: 1,
  });

  if (!reportId) {
    return (
      <div className="container mx-auto p-4 max-w-5xl">
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          缺少 reportId 参数
        </div>
      </div>
    );
  }

  if (q.isLoading) {
    return (
      <div className="container mx-auto p-4 max-w-5xl">
        <div className="rounded-lg border border-border/50 bg-card/30 p-8 text-center text-sm text-muted-foreground">
          <Loader2 className="size-5 mx-auto animate-spin mb-2" />
          加载报告…
        </div>
      </div>
    );
  }

  if (q.isError || !q.data) {
    return (
      <div className="container mx-auto p-4 max-w-5xl space-y-4">
        <Link
          to="/analysis"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" /> 返回列表
        </Link>
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle className="size-4" /> 加载失败
          </div>
          <div className="mt-1 text-xs opacity-80">
            {(q.error as Error & { friendly?: string })?.friendly ??
              (q.error as Error)?.message ??
              "未知错误"}
          </div>
        </div>
      </div>
    );
  }

  const r = q.data;
  const isErr = r.status === "error";

  // 找到各层的 raw payload
  const findPayload = (layer: string): AIRawPayload | undefined =>
    r.raw_payloads.find((p) => p.layer === layer);

  return (
    <div className="container mx-auto p-4 max-w-5xl space-y-6">
      <Link
        to="/analysis"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> 返回列表
      </Link>

      {/* Hero */}
      <div
        className={cn(
          "rounded-xl border p-5 space-y-3",
          isErr ? "border-destructive/40 bg-destructive/5" : "border-border/50 bg-card/40",
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{r.symbol}</span>
              <span>·</span>
              <span>{r.tf}</span>
              <span>·</span>
              <span className="uppercase">{r.model_tier}</span>
              {r.thinking_enabled && (
                <Badge variant="secondary" className="text-[9px] px-1 py-0">
                  thinking
                </Badge>
              )}
              <Badge variant={isErr ? "destructive" : "outline"} className="text-[10px]">
                {isErr ? "失败" : "成功"}
              </Badge>
            </div>
            <h1
              className={cn(
                "mt-1 text-xl font-semibold leading-tight",
                isErr ? "text-destructive" : "text-foreground",
              )}
            >
              {r.one_line || (isErr ? "深度分析失败" : "（无摘要）")}
            </h1>
            <div className="mt-1 text-xs text-muted-foreground">
              {fmtTs(r.ts)} · id={r.id}
            </div>
          </div>
          <div className="text-right text-xs text-muted-foreground space-y-1">
            <div>
              tokens <span className="text-foreground">{r.total_tokens.toLocaleString()}</span>
            </div>
            <div>
              延迟{" "}
              <span className="text-foreground">{(r.total_latency_ms / 1000).toFixed(1)}s</span>
            </div>
          </div>
        </div>
        {isErr && r.error_reason && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive whitespace-pre-wrap">
            {r.error_reason}
          </div>
        )}
      </div>

      {/* Markdown 报告 */}
      <div className="rounded-xl border border-border/50 bg-card/40 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <FileText className="size-4 text-primary" /> 详细分析报告
          </h2>
          {r.report_md && <CopyButton text={r.report_md} />}
        </div>
        {r.report_md ? (
          <MarkdownLite source={r.report_md} />
        ) : (
          <div className="text-sm text-muted-foreground">（无报告正文，请查看下方 raw_payloads 排查）</div>
        )}
      </div>

      {/* 图 5 · AI 交互过程原文 */}
      <div className="rounded-xl border border-border/50 bg-card/40 p-5">
        <div className="mb-3">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <MessageSquare className="size-4 text-primary" />
            AI 交互过程原文（System · User · Raw Response · 跨模型对照数据切片）
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            点击任一项展开查看完整原文；前三项用于复盘本次 AI "看了什么/想了什么/输出了什么"；
            第四项为已剥离我方规则/指令的<span className="text-emerald-400">纯数据切片</span>，
            专供你一键复制给其他 AI 做独立判断，对比哪家模型的方向更准。
          </p>
        </div>

        <div className="space-y-2">
          {(["trend", "money_flow", "trade_plan", "deep_analyze"] as const).map((layer) => {
            const meta = LAYER_META[layer];
            const p = findPayload(layer);
            if (!p) return null;
            return (
              <div key={layer} className="space-y-1.5">
                <div className="text-xs text-muted-foreground flex items-center gap-2">
                  <Cpu className="size-3" />
                  <span className="font-medium text-foreground">{meta.title}</span>
                  <span>·</span>
                  <span>{p.model}</span>
                  <span>·</span>
                  <span>{p.tokens_total.toLocaleString()} tok</span>
                  <span>·</span>
                  <span>{(p.latency_ms / 1000).toFixed(1)}s</span>
                </div>
                <RawPayloadRow
                  title={`System Prompt`}
                  hint="AI 人设/裁决框架/输出格式契约"
                  Icon={MessageSquare}
                  text={p.system_prompt}
                />
                <RawPayloadRow
                  title={`User Prompt（本轮喂给 AI 的完整数据）`}
                  hint="规则约束 + 投影 input + 历史 narrative"
                  Icon={FileText}
                  text={p.user_prompt}
                />
                <RawPayloadRow
                  title={`Raw Response（AI 返回的原始 JSON / Markdown 原文）`}
                  hint="模型最终输出（解析前）"
                  Icon={Scale}
                  text={p.raw_response}
                />
                <div className="border-b border-border/30 my-2" />
              </div>
            );
          })}

          <RawPayloadRow
            title="跨模型对照数据切片（纯数据 · 无规则 · 无指令）"
            hint="已剥离我方规则/指令的 LLM 输入 JSON；保留完整行情/链上/结构/关键位/新闻数据 — 复制给其他 AI 做独立判断"
            Icon={Scale}
            text={r.data_slice}
          />
        </div>
      </div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";

import { fetchLogsMeta } from "@/lib/api";
import type { LogLevel } from "@/lib/types";
import { cn } from "@/lib/utils";
import { levelColor } from "@/lib/logs-helpers";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const LEVELS: LogLevel[] = ["DEBUG", "INFO", "WARNING", "ERROR"];

export interface LogFilter {
  levels: LogLevel[];
  loggers: string[];
  keyword: string;
  symbol: string;
  from_ts: string;
  to_ts: string;
  limit: number;
}

export const EMPTY_FILTER: LogFilter = {
  levels: [],
  loggers: [],
  keyword: "",
  symbol: "",
  from_ts: "",
  to_ts: "",
  limit: 200,
};

interface Props {
  filter: LogFilter;
  onChange: (f: LogFilter) => void;
  /** 是否显示分页 limit（实时尾部无需） */
  showLimit?: boolean;
}

export function LogFilterBar({ filter, onChange, showLimit = true }: Props) {
  const metaQ = useQuery({
    queryKey: ["logs-meta"],
    queryFn: fetchLogsMeta,
    staleTime: 10 * 60_000,
  });

  const toggleLevel = (lv: LogLevel) => {
    const next = filter.levels.includes(lv)
      ? filter.levels.filter((x) => x !== lv)
      : [...filter.levels, lv];
    onChange({ ...filter, levels: next });
  };

  const toggleLogger = (prefix: string) => {
    const next = filter.loggers.includes(prefix)
      ? filter.loggers.filter((x) => x !== prefix)
      : [...filter.loggers, prefix];
    onChange({ ...filter, loggers: next });
  };

  const reset = () => onChange(EMPTY_FILTER);

  return (
    <div className="space-y-3 rounded-md border border-border/40 bg-background/40 p-3">
      {/* Levels */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-12 shrink-0 text-xs text-muted-foreground">级别</span>
        <div className="flex flex-wrap gap-1.5">
          {LEVELS.map((lv) => {
            const active = filter.levels.includes(lv);
            return (
              <button
                key={lv}
                onClick={() => toggleLevel(lv)}
                className={cn(
                  "rounded-md px-2 py-0.5 text-xs font-medium transition-all",
                  active
                    ? levelColor(lv)
                    : "bg-muted/40 text-muted-foreground hover:bg-muted",
                )}
              >
                {lv}
              </button>
            );
          })}
        </div>
        {filter.levels.length === 0 && (
          <span className="text-[10px] italic text-muted-foreground">
            未选择 → 默认全部
          </span>
        )}
      </div>

      {/* Logger 前缀 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-12 shrink-0 text-xs text-muted-foreground">模块</span>
        <div className="flex flex-wrap gap-1.5">
          {(metaQ.data?.logger_prefixes ?? []).map((pfx) => {
            const active = filter.loggers.includes(pfx);
            return (
              <button
                key={pfx}
                onClick={() => toggleLogger(pfx)}
                className={cn(
                  "rounded-full px-2.5 py-0.5 text-xs font-mono transition-colors",
                  active
                    ? "bg-primary/20 text-primary ring-1 ring-primary/40"
                    : "bg-muted/40 text-muted-foreground hover:bg-muted",
                )}
              >
                {pfx}
              </button>
            );
          })}
        </div>
      </div>

      {/* keyword / symbol */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-12 shrink-0 text-xs text-muted-foreground">关键词</span>
        <Input
          className="h-8 w-64"
          placeholder="消息中包含…"
          value={filter.keyword}
          onChange={(e) => onChange({ ...filter, keyword: e.target.value })}
        />
        <span className="ml-2 text-xs text-muted-foreground">币种</span>
        <Input
          className="h-8 w-24 font-mono uppercase"
          placeholder="BTC"
          value={filter.symbol}
          onChange={(e) =>
            onChange({ ...filter, symbol: e.target.value.toUpperCase() })
          }
        />
      </div>

      {/* 时间 + limit */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-12 shrink-0 text-xs text-muted-foreground">时间</span>
        <Input
          className="h-8 w-52 font-mono text-xs"
          type="datetime-local"
          value={filter.from_ts}
          onChange={(e) => onChange({ ...filter, from_ts: e.target.value })}
        />
        <span className="text-xs text-muted-foreground">→</span>
        <Input
          className="h-8 w-52 font-mono text-xs"
          type="datetime-local"
          value={filter.to_ts}
          onChange={(e) => onChange({ ...filter, to_ts: e.target.value })}
        />
        {showLimit && (
          <>
            <span className="ml-2 text-xs text-muted-foreground">每页</span>
            <Select
              value={String(filter.limit)}
              onValueChange={(v) =>
                onChange({ ...filter, limit: Number(v) })
              }
            >
              <SelectTrigger className="h-8 w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[50, 100, 200, 500].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        )}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={reset}
          disabled={isFilterEmpty(filter)}
        >
          <RotateCcw className="mr-1 h-3.5 w-3.5" />
          重置
        </Button>
      </div>
    </div>
  );
}

export function isFilterEmpty(f: LogFilter): boolean {
  return (
    f.levels.length === 0 &&
    f.loggers.length === 0 &&
    !f.keyword &&
    !f.symbol &&
    !f.from_ts &&
    !f.to_ts
  );
}

/** datetime-local → ISO（UTC） */
export function toIsoIfAny(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

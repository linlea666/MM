import { memo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { LogEntry } from "@/lib/types";
import { formatIsoTs } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { levelColor } from "@/lib/logs-helpers";

import { Badge } from "@/components/ui/badge";

interface Props {
  row: LogEntry;
  defaultOpen?: boolean;
}

export const LogRow = memo(function LogRow({ row, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const hasDetail =
    !!row.traceback || (row.context && Object.keys(row.context).length > 0);

  return (
    <div
      className={cn(
        "rounded-md border border-border/30 bg-background/40 text-xs transition-colors",
        row.level === "ERROR" && "border-destructive/40 bg-destructive/5",
        row.level === "WARNING" && "border-warning/30 bg-warning/5",
      )}
    >
      <div
        className={cn(
          "flex cursor-pointer items-start gap-2 px-2.5 py-1.5",
          hasDetail && "hover:bg-accent/30",
        )}
        onClick={() => hasDetail && setOpen((v) => !v)}
      >
        {hasDetail ? (
          open ? (
            <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )
        ) : (
          <span className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        )}
        <span className="shrink-0 font-mono num text-[11px] text-muted-foreground">
          {formatIsoTs(row.ts)}
        </span>
        <span
          className={cn(
            "shrink-0 rounded px-1 py-0.5 text-[10px] font-medium",
            levelColor(row.level),
          )}
        >
          {row.level}
        </span>
        <span className="shrink-0 font-mono text-[11px] text-foreground/70">
          {row.logger}
        </span>
        <span className="flex-1 break-words text-foreground/90">
          {row.message}
        </span>
        {row.tags.length > 0 && (
          <div className="flex shrink-0 flex-wrap gap-1">
            {row.tags.slice(0, 3).map((t) => (
              <Badge
                key={t}
                variant="secondary"
                className="px-1 py-0 text-[10px] font-normal leading-4"
              >
                {t}
              </Badge>
            ))}
          </div>
        )}
      </div>
      {open && hasDetail && (
        <div className="border-t border-border/30 bg-background/60 px-2.5 py-2 text-[11px]">
          {row.context && Object.keys(row.context).length > 0 && (
            <>
              <div className="mb-1 text-[10px] font-medium uppercase text-muted-foreground">
                context
              </div>
              <pre className="overflow-x-auto rounded bg-muted/40 p-2 font-mono text-[11px]">
                {JSON.stringify(row.context, null, 2)}
              </pre>
            </>
          )}
          {row.traceback && (
            <>
              <div className="mt-2 mb-1 text-[10px] font-medium uppercase text-destructive/80">
                traceback
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-destructive/5 p-2 font-mono text-[11px] text-destructive/90">
                {row.traceback}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
});

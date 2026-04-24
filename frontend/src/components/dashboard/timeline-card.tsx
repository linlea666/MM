import type { TimelineEvent } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { relativeTime, severityColor } from "@/lib/ui-helpers";
import { cn } from "@/lib/utils";

interface Props {
  events: TimelineEvent[];
}

export function TimelineCard({ events }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>近期异动</CardTitle>
      </CardHeader>
      <CardContent>
        {events.length === 0 ? (
          <div className="py-4 text-center text-sm text-muted-foreground">
            暂无异动
          </div>
        ) : (
          <ScrollArea className="h-[320px] pr-2">
            <ol className="space-y-2">
              {events.map((ev, i) => (
                <li
                  key={`${ev.ts}-${ev.kind}-${ev.headline}`}
                  className="flex gap-3 rounded-md border border-border/40 bg-background/40 p-2.5 animate-in fade-in slide-in-from-top-2 duration-500"
                  style={{ animationDelay: `${Math.min(i, 3) * 40}ms` }}
                >
                  <div className="flex flex-col items-center pt-0.5">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase",
                        severityColor(ev.severity),
                      )}
                    >
                      {ev.kind}
                    </span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">
                        {ev.headline}
                      </span>
                      <span className="shrink-0 font-mono text-[10px] text-muted-foreground num">
                        {relativeTime(ev.ts)}
                      </span>
                    </div>
                    {ev.detail && (
                      <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                        {ev.detail}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

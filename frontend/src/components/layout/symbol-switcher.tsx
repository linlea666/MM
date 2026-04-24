import { useQuery } from "@tanstack/react-query";
import { listSubscriptions } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ALLOWED_TFS, useSymbolStore, type Tf } from "@/stores/symbol-store";
import { Loader2 } from "lucide-react";

export function SymbolSwitcher() {
  const symbol = useSymbolStore((s) => s.symbol);
  const setSymbol = useSymbolStore((s) => s.setSymbol);
  const tf = useSymbolStore((s) => s.tf);
  const setTf = useSymbolStore((s) => s.setTf);

  const { data: subs, isLoading } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: listSubscriptions,
    refetchInterval: 30_000,
  });

  const active = (subs ?? []).filter((s) => s.active);

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        币种
      </div>
      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : (
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-8 w-28">
            <SelectValue placeholder="选择币种" />
          </SelectTrigger>
          <SelectContent>
            {active.length === 0 ? (
              <SelectItem value={symbol}>{symbol}</SelectItem>
            ) : (
              active.map((s) => (
                <SelectItem key={s.symbol} value={s.symbol}>
                  {s.symbol}
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      )}

      <div className="ml-2 flex items-center gap-1 text-xs text-muted-foreground">
        周期
      </div>
      <Select value={tf} onValueChange={(v) => setTf(v as Tf)}>
        <SelectTrigger className="h-8 w-20">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ALLOWED_TFS.map((t) => (
            <SelectItem key={t} value={t}>
              {t}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

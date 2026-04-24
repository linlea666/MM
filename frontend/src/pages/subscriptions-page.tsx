import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Loader2,
  Plus,
  Radar,
  Trash2,
  X,
} from "lucide-react";

import {
  createSubscription,
  deleteSubscription,
  listSubscriptions,
  updateSubscription,
} from "@/lib/api";
import type { Subscription } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";
import { useSymbolStore } from "@/stores/symbol-store";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";

type Banner = {
  kind: "success" | "error";
  text: string;
};

const SYMBOL_RE = /^[A-Za-z0-9]{2,10}$/;

export default function SubscriptionsPage() {
  const qc = useQueryClient();
  const currentSymbol = useSymbolStore((s) => s.symbol);
  const setSymbol = useSymbolStore((s) => s.setSymbol);

  const [input, setInput] = useState("");
  const [activateOnAdd, setActivateOnAdd] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [banner, setBanner] = useState<Banner | null>(null);

  const { data: subs, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: listSubscriptions,
    refetchInterval: 15_000,
  });

  const sorted = useMemo(
    () =>
      (subs ?? []).slice().sort((a, b) => {
        if (a.active !== b.active) return a.active ? -1 : 1;
        return a.display_order - b.display_order;
      }),
    [subs],
  );

  const notify = (b: Banner) => {
    setBanner(b);
    window.setTimeout(() => setBanner(null), 3000);
  };

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["subscriptions"] });
    qc.invalidateQueries({ queryKey: ["system-health"] });
  };

  // ─── mutations ─────────────────────────────────────────

  const addMut = useMutation({
    mutationFn: ({ symbol, active }: { symbol: string; active: boolean }) =>
      createSubscription(symbol, active),
    onSuccess: (row) => {
      invalidate();
      setInput("");
      notify({ kind: "success", text: `已添加 ${row.symbol}` });
    },
    onError: (err: Error & { friendly?: string }) => {
      notify({ kind: "error", text: err.friendly ?? err.message });
    },
  });

  const toggleMut = useMutation({
    mutationFn: ({ symbol, active }: { symbol: string; active: boolean }) =>
      updateSubscription(symbol, { active }),
    onSuccess: (row) => {
      invalidate();
      notify({
        kind: "success",
        text: `${row.symbol} 已${row.active ? "激活" : "停用"}`,
      });
    },
    onError: (err: Error & { friendly?: string }) => {
      notify({ kind: "error", text: err.friendly ?? err.message });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (symbol: string) => deleteSubscription(symbol),
    onSuccess: (_void, symbol) => {
      invalidate();
      setConfirmDelete(null);
      notify({ kind: "success", text: `已删除 ${symbol}` });
      if (symbol === currentSymbol) {
        const fallback =
          (subs ?? []).find((s) => s.active && s.symbol !== symbol)?.symbol
          ?? (subs ?? []).find((s) => s.symbol !== symbol)?.symbol;
        if (fallback) setSymbol(fallback);
      }
    },
    onError: (err: Error & { friendly?: string }) => {
      notify({ kind: "error", text: err.friendly ?? err.message });
    },
  });

  // ─── handlers ──────────────────────────────────────────

  const submitAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const s = input.trim().toUpperCase();
    if (!SYMBOL_RE.test(s)) {
      notify({
        kind: "error",
        text: "币种需 2–10 位字母或数字，如 BTC / ETH / SOL",
      });
      return;
    }
    if ((subs ?? []).some((x) => x.symbol === s)) {
      notify({ kind: "error", text: `${s} 已在订阅列表中` });
      return;
    }
    addMut.mutate({ symbol: s, active: activateOnAdd });
  };

  // ─── render ────────────────────────────────────────────

  return (
    <div className="grid gap-4">
      {/* 添加表单 */}
      <Card>
        <CardHeader>
          <CardTitle>添加币种</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="flex flex-wrap items-center gap-3" onSubmit={submitAdd}>
            <Input
              className="h-9 w-40 font-mono uppercase"
              placeholder="BTC / ETH / SOL"
              value={input}
              maxLength={10}
              onChange={(e) => setInput(e.target.value.toUpperCase())}
              disabled={addMut.isPending}
              autoFocus
            />
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Switch
                checked={activateOnAdd}
                onCheckedChange={setActivateOnAdd}
                disabled={addMut.isPending}
              />
              <span>添加后立即激活</span>
            </label>
            <Button type="submit" disabled={addMut.isPending || !input.trim()}>
              {addMut.isPending ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <Plus className="mr-1.5 h-4 w-4" />
              )}
              添加
            </Button>
            <div className="ml-auto text-xs text-muted-foreground">
              激活后采集器将为该币种定时拉取 HFD 指标。停用则仅保留订阅配置，
              不消耗 API 配额。
            </div>
          </form>
        </CardContent>
      </Card>

      {/* 提示横条 */}
      {banner && (
        <div
          role="status"
          className={cn(
            "rounded-md border px-3 py-2 text-sm",
            banner.kind === "success"
              ? "border-bullish/40 bg-bullish/10 text-bullish"
              : "border-destructive/40 bg-destructive/10 text-destructive",
          )}
        >
          {banner.text}
        </div>
      )}

      {/* 列表 */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>订阅列表</CardTitle>
          <div className="text-xs text-muted-foreground">
            {sorted.length > 0 && (
              <>
                共 {sorted.length} 个 ·{" "}
                <span className="text-bullish">
                  {sorted.filter((s) => s.active).length} 激活
                </span>
                {" / "}
                <span>{sorted.filter((s) => !s.active).length} 停用</span>
              </>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <TableSkeleton />
          ) : isError ? (
            <div className="flex flex-col items-center gap-2 p-8 text-sm text-muted-foreground">
              <X className="h-6 w-6 text-destructive" />
              加载失败：{(error as Error & { friendly?: string })?.friendly ?? String(error)}
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                重试
              </Button>
            </div>
          ) : sorted.length === 0 ? (
            <div className="flex flex-col items-center gap-2 p-10 text-sm text-muted-foreground">
              <Radar className="h-6 w-6" />
              尚未订阅任何币种。上方添加 BTC / ETH 开始。
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border/40 text-xs text-muted-foreground">
                  <tr className="text-left">
                    <Th>币种</Th>
                    <Th>状态</Th>
                    <Th>激活 / 停用</Th>
                    <Th>添加时间</Th>
                    <Th>最近查看</Th>
                    <Th className="text-right">操作</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {sorted.map((row) => (
                    <Row
                      key={row.symbol}
                      row={row}
                      isCurrent={row.symbol === currentSymbol}
                      confirmingDelete={confirmDelete === row.symbol}
                      onToggle={(active) =>
                        toggleMut.mutate({ symbol: row.symbol, active })
                      }
                      onSetCurrent={() => {
                        setSymbol(row.symbol);
                        notify({
                          kind: "success",
                          text: `已切换到 ${row.symbol}`,
                        });
                      }}
                      onRequestDelete={() => setConfirmDelete(row.symbol)}
                      onCancelDelete={() => setConfirmDelete(null)}
                      onConfirmDelete={() => deleteMut.mutate(row.symbol)}
                      togglePending={
                        toggleMut.isPending &&
                        toggleMut.variables?.symbol === row.symbol
                      }
                      deletePending={
                        deleteMut.isPending && deleteMut.variables === row.symbol
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ─── 表格行 ───────────────────────────────────────────────

interface RowProps {
  row: Subscription;
  isCurrent: boolean;
  confirmingDelete: boolean;
  togglePending: boolean;
  deletePending: boolean;
  onToggle: (active: boolean) => void;
  onSetCurrent: () => void;
  onRequestDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

function Row({
  row,
  isCurrent,
  confirmingDelete,
  togglePending,
  deletePending,
  onToggle,
  onSetCurrent,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: RowProps) {
  return (
    <tr
      className={cn(
        "transition-colors hover:bg-accent/30",
        isCurrent && "bg-primary/5",
      )}
    >
      <Td>
        <div className="flex items-center gap-2">
          <span className="font-mono text-base font-semibold">{row.symbol}</span>
          {isCurrent && (
            <Badge variant="default" className="font-normal">
              当前
            </Badge>
          )}
        </div>
      </Td>
      <Td>
        {row.active ? (
          <Badge variant="success" className="font-normal">
            激活
          </Badge>
        ) : (
          <Badge variant="secondary" className="font-normal">
            停用
          </Badge>
        )}
      </Td>
      <Td>
        <div className="flex items-center gap-2">
          <Switch
            checked={row.active}
            onCheckedChange={onToggle}
            disabled={togglePending}
            aria-label={`${row.active ? "停用" : "激活"} ${row.symbol}`}
          />
          {togglePending && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
          )}
        </div>
      </Td>
      <Td className="font-mono num text-xs text-muted-foreground">
        {formatDateTime(row.added_at)}
      </Td>
      <Td className="font-mono num text-xs text-muted-foreground">
        {row.last_viewed_at ? formatDateTime(row.last_viewed_at) : "—"}
      </Td>
      <Td className="text-right">
        <div className="flex items-center justify-end gap-1.5">
          {!isCurrent && (
            <Button
              size="sm"
              variant="outline"
              onClick={onSetCurrent}
              disabled={!row.active}
              title={row.active ? "切换到该币种" : "请先激活后再切换"}
            >
              设为当前
            </Button>
          )}
          {!confirmingDelete ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={onRequestDelete}
              disabled={deletePending}
              aria-label={`删除 ${row.symbol}`}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          ) : (
            <div className="inline-flex items-center gap-1 rounded-md border border-destructive/40 bg-destructive/10 px-1.5 py-0.5">
              <span className="text-xs text-destructive">确认？</span>
              <Button
                size="sm"
                variant="destructive"
                className="h-6 px-2"
                onClick={onConfirmDelete}
                disabled={deletePending}
              >
                {deletePending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Check className="h-3 w-3" />
                )}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 px-2"
                onClick={onCancelDelete}
                disabled={deletePending}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          )}
        </div>
      </Td>
    </tr>
  );
}

// ─── 小部件 ─────────────────────────────────────────────

function Th({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th className={cn("px-4 py-2.5 font-medium", className)}>{children}</th>
  );
}

function Td({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={cn("px-4 py-2.5 align-middle", className)}>{children}</td>;
}

function TableSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

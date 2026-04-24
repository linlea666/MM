import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Diff,
  Loader2,
  RotateCcw,
  Save,
  Undo2,
  X,
} from "lucide-react";

import {
  fetchConfigMeta,
  fetchConfigSnapshot,
  patchConfig,
  previewConfig,
  resetConfig,
} from "@/lib/api";
import type {
  ConfigItemMeta,
  ConfigMetaResp,
  ConfigSnapshotResp,
  ConfigValue,
} from "@/lib/types";
import {
  coerceToFieldValue,
  formatForDisplay,
  getByPath,
  valuesEqual,
} from "@/lib/config-utils";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

import { AuditPanel } from "@/components/config/audit-panel";
import { ConfigField } from "@/components/config/config-field";

type Banner = { kind: "success" | "error" | "info"; text: string };

export default function ConfigPage() {
  const qc = useQueryClient();

  const metaQ = useQuery<ConfigMetaResp>({
    queryKey: ["config-meta"],
    queryFn: fetchConfigMeta,
    staleTime: 5 * 60_000,
  });
  const snapQ = useQuery<ConfigSnapshotResp>({
    queryKey: ["config-snapshot"],
    queryFn: fetchConfigSnapshot,
    refetchInterval: 30_000,
  });

  const groups = metaQ.data?.groups ?? [];
  const items = metaQ.data?.items ?? {};
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  useEffect(() => {
    if (!activeGroup && groups.length > 0) setActiveGroup(groups[0].id);
  }, [groups, activeGroup]);

  // 分组后的 Tier 1 items（仅展示有配置项的分组）
  const groupedItems = useMemo(() => {
    const buckets = new Map<string, { key: string; meta: ConfigItemMeta }[]>();
    for (const [k, m] of Object.entries(items)) {
      const g = m.group;
      if (!buckets.has(g)) buckets.set(g, []);
      buckets.get(g)!.push({ key: k, meta: m });
    }
    return buckets;
  }, [items]);

  const visibleGroups = useMemo(
    () => groups.filter((g) => (groupedItems.get(g.id)?.length ?? 0) > 0),
    [groups, groupedItems],
  );

  useEffect(() => {
    if (
      activeGroup &&
      visibleGroups.length > 0 &&
      !visibleGroups.some((g) => g.id === activeGroup)
    ) {
      setActiveGroup(visibleGroups[0].id);
    }
  }, [visibleGroups, activeGroup]);

  // dirty values：key → 未保存的新值
  const [dirty, setDirty] = useState<Record<string, ConfigValue>>({});
  const [banner, setBanner] = useState<Banner | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [confirmResetAll, setConfirmResetAll] = useState(false);

  const notify = (b: Banner) => {
    setBanner(b);
    window.setTimeout(() => setBanner(null), 3000);
  };

  // override 集合（用于渲染徽标）
  const overriddenKeys = useMemo(() => {
    const s = new Set<string>();
    for (const r of snapQ.data?.overrides ?? []) s.add(r.key);
    return s;
  }, [snapQ.data]);

  const runningValues = snapQ.data?.values ?? {};

  // ─── mutations ───────────────────────────────────

  const patchMut = useMutation({
    mutationFn: (payload: Record<string, ConfigValue>) =>
      patchConfig({
        items: payload,
        updated_by: "ui",
        reason: "UI bulk patch",
      }),
    onSuccess: (resp) => {
      notify({
        kind: "success",
        text: `已保存 ${resp.count} 项`,
      });
      setDirty({});
      setShowDiff(false);
      qc.invalidateQueries({ queryKey: ["config-snapshot"] });
      qc.invalidateQueries({ queryKey: ["config-audit"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error & { friendly?: string }) => {
      notify({ kind: "error", text: err.friendly ?? err.message });
    },
  });

  const resetKeyMut = useMutation({
    mutationFn: (key: string) =>
      resetConfig({ key, updated_by: "ui", reason: "UI reset single" }),
    onSuccess: (_resp, key) => {
      notify({ kind: "success", text: `已重置 ${key}` });
      setDirty((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      qc.invalidateQueries({ queryKey: ["config-snapshot"] });
      qc.invalidateQueries({ queryKey: ["config-audit"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error & { friendly?: string }) => {
      notify({ kind: "error", text: err.friendly ?? err.message });
    },
  });

  const resetAllMut = useMutation({
    mutationFn: () =>
      resetConfig({
        updated_by: "ui",
        reason: "UI reset all",
      }),
    onSuccess: (resp) => {
      notify({
        kind: "success",
        text: `已全量重置（${resp.removed} 项 override）`,
      });
      setDirty({});
      setConfirmResetAll(false);
      qc.invalidateQueries({ queryKey: ["config-snapshot"] });
      qc.invalidateQueries({ queryKey: ["config-audit"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error & { friendly?: string }) => {
      notify({ kind: "error", text: err.friendly ?? err.message });
      setConfirmResetAll(false);
    },
  });

  const previewQ = useQuery({
    queryKey: ["config-preview", dirty],
    queryFn: () => previewConfig(dirty),
    enabled: showDiff && Object.keys(dirty).length > 0,
  });

  // ─── 取值 / 改值 ─────────────────────────────────

  const getFieldValue = (key: string, meta: ConfigItemMeta): ConfigValue => {
    if (key in dirty) return dirty[key];
    return coerceToFieldValue(getByPath(runningValues, key), meta);
  };

  const getDefaultValue = (key: string, meta: ConfigItemMeta): ConfigValue => {
    // 通过 preview 能拿到，但简化：直接用当前运行值（未覆盖时就是默认）
    // 真正的 default 在后端 settings.rules_defaults；前端从 snapshot 推断。
    // 若该 key 被 override 则运行值≠默认；此处省略拉单项 meta/default API。
    return coerceToFieldValue(getByPath(runningValues, key), meta);
  };

  const setFieldValue = (key: string, meta: ConfigItemMeta, v: ConfigValue) => {
    const current = coerceToFieldValue(getByPath(runningValues, key), meta);
    setDirty((d) => {
      const next = { ...d };
      if (valuesEqual(v, current)) {
        delete next[key]; // 改回当前运行值 → 自动退出 dirty
      } else {
        next[key] = v;
      }
      return next;
    });
  };

  const discardAll = () => {
    setDirty({});
    setShowDiff(false);
  };

  const dirtyCount = Object.keys(dirty).length;
  const hasDanger = Object.keys(dirty).some((k) => items[k]?.danger);

  // ─── 渲染 ────────────────────────────────────────

  if (metaQ.isLoading || snapQ.isLoading) {
    return <PageSkeleton />;
  }
  if (metaQ.isError || snapQ.isError) {
    const err = (metaQ.error ?? snapQ.error) as Error & { friendly?: string };
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
          <AlertTriangle className="h-8 w-8 text-destructive" />
          <div className="text-sm text-muted-foreground">
            配置加载失败：{err?.friendly ?? err?.message}
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              metaQ.refetch();
              snapQ.refetch();
            }}
          >
            重试
          </Button>
        </CardContent>
      </Card>
    );
  }

  const activeItems =
    activeGroup && groupedItems.has(activeGroup)
      ? groupedItems.get(activeGroup)!
      : [];

  // 按 subgroup 二次分组
  const subgroups = new Map<string, { key: string; meta: ConfigItemMeta }[]>();
  for (const it of activeItems) {
    const sg = it.meta.subgroup ?? "（默认）";
    if (!subgroups.has(sg)) subgroups.set(sg, []);
    subgroups.get(sg)!.push(it);
  }

  return (
    <div className="grid gap-4 pb-20">
      {banner && (
        <div
          className={cn(
            "rounded-md border px-3 py-2 text-sm",
            banner.kind === "success"
              ? "border-bullish/40 bg-bullish/10 text-bullish"
              : banner.kind === "error"
                ? "border-destructive/40 bg-destructive/10 text-destructive"
                : "border-primary/40 bg-primary/10 text-primary",
          )}
        >
          {banner.text}
        </div>
      )}

      <Tabs defaultValue="form">
        <TabsList>
          <TabsTrigger value="form">规则参数</TabsTrigger>
          <TabsTrigger value="audit">审计历史</TabsTrigger>
        </TabsList>

        {/* ─── 规则参数 ─── */}
        <TabsContent value="form">
          <div className="grid gap-4 lg:grid-cols-12">
            {/* 左：分组导航 */}
            <aside className="lg:col-span-3">
              <Card>
                <CardHeader>
                  <CardTitle>配置分组</CardTitle>
                </CardHeader>
                <CardContent className="p-2">
                  <nav className="flex flex-col gap-0.5">
                    {visibleGroups.map((g) => {
                      const count = groupedItems.get(g.id)?.length ?? 0;
                      const dirtyInGroup = Object.keys(dirty).filter(
                        (k) => items[k]?.group === g.id,
                      ).length;
                      const overriddenInGroup = [...overriddenKeys].filter(
                        (k) => items[k]?.group === g.id,
                      ).length;
                      return (
                        <button
                          key={g.id}
                          onClick={() => setActiveGroup(g.id)}
                          className={cn(
                            "flex items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                            activeGroup === g.id
                              ? "bg-secondary text-secondary-foreground"
                              : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                          )}
                        >
                          <span>{g.label}</span>
                          <div className="flex items-center gap-1">
                            {dirtyInGroup > 0 && (
                              <Badge
                                variant="default"
                                className="h-4 min-w-[20px] px-1 text-[10px]"
                              >
                                {dirtyInGroup}
                              </Badge>
                            )}
                            {overriddenInGroup > 0 && (
                              <Badge
                                variant="warning"
                                className="h-4 min-w-[20px] px-1 text-[10px]"
                              >
                                {overriddenInGroup}
                              </Badge>
                            )}
                            <span className="font-mono text-[10px] opacity-60">
                              {count}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </nav>
                </CardContent>
              </Card>

              {/* 全量重置 */}
              <Card className="mt-4">
                <CardContent className="flex flex-col gap-2 p-4 text-sm">
                  <div className="font-medium">全量重置</div>
                  <div className="text-xs text-muted-foreground">
                    清空所有覆盖，所有配置回到 YAML 默认值。本操作会立即生效并写审计。
                  </div>
                  {!confirmResetAll ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      onClick={() => setConfirmResetAll(true)}
                      disabled={overriddenKeys.size === 0 || resetAllMut.isPending}
                    >
                      <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                      重置全部 ({overriddenKeys.size})
                    </Button>
                  ) : (
                    <div className="flex items-center gap-2">
                      <Button
                        variant="destructive"
                        size="sm"
                        className="flex-1"
                        onClick={() => resetAllMut.mutate()}
                        disabled={resetAllMut.isPending}
                      >
                        {resetAllMut.isPending ? (
                          <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Check className="mr-1 h-3.5 w-3.5" />
                        )}
                        确认重置
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setConfirmResetAll(false)}
                        disabled={resetAllMut.isPending}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            </aside>

            {/* 右：表单 */}
            <div className="lg:col-span-9 space-y-4">
              {activeGroup && (
                <Card>
                  <CardHeader>
                    <CardTitle>
                      {visibleGroups.find((g) => g.id === activeGroup)?.label}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    {[...subgroups.entries()].map(([sg, list]) => (
                      <div key={sg} className="space-y-2">
                        <div className="flex items-center gap-2 border-b border-border/40 pb-1 text-xs font-medium text-muted-foreground">
                          {sg}
                          <span className="font-mono text-[10px] opacity-70">
                            · {list.length} 项
                          </span>
                        </div>
                        <div className="grid gap-2 md:grid-cols-2">
                          {list.map((it) => {
                            const val = getFieldValue(it.key, it.meta);
                            const def = getDefaultValue(it.key, it.meta);
                            const isOv = overriddenKeys.has(it.key);
                            const isDirty = it.key in dirty;
                            return (
                              <ConfigField
                                key={it.key}
                                keyPath={it.key}
                                meta={it.meta}
                                value={val}
                                defaultValue={def}
                                isOverridden={isOv}
                                isDirty={isDirty}
                                onChange={(v) => setFieldValue(it.key, it.meta, v)}
                                onReset={
                                  isOv && !resetKeyMut.isPending
                                    ? () => resetKeyMut.mutate(it.key)
                                    : undefined
                                }
                              />
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Diff 预览 */}
              {showDiff && dirtyCount > 0 && (
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between space-y-0">
                    <CardTitle>本次修改预览</CardTitle>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowDiff(false)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </CardHeader>
                  <CardContent>
                    {previewQ.isLoading ? (
                      <Skeleton className="h-24 w-full" />
                    ) : previewQ.isError ? (
                      <div className="text-sm text-destructive">
                        预览失败：
                        {
                          (previewQ.error as Error & { friendly?: string })
                            ?.friendly
                        }
                      </div>
                    ) : (
                      <DiffTable
                        dirty={dirty}
                        items={items}
                        before={previewQ.data?.snapshot_before ?? {}}
                        after={previewQ.data?.snapshot_after ?? {}}
                      />
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </TabsContent>

        {/* ─── 审计历史 ─── */}
        <TabsContent value="audit">
          <AuditPanel />
        </TabsContent>
      </Tabs>

      {/* 底部粘贴栏 */}
      {dirtyCount > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border/60 bg-background/95 px-4 py-2.5 backdrop-blur">
          <div className="mx-auto flex max-w-[1680px] items-center gap-3">
            <Badge variant="default" className="font-normal">
              {dirtyCount} 项未保存
            </Badge>
            {hasDanger && (
              <Badge variant="destructive" className="gap-1 font-normal">
                <AlertTriangle className="h-3 w-3" />
                含关键改动
              </Badge>
            )}
            <div className="ml-auto flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setShowDiff((v) => !v)}
              >
                <Diff className="mr-1.5 h-3.5 w-3.5" />
                {showDiff ? "收起差异" : "查看差异"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={discardAll}
                disabled={patchMut.isPending}
              >
                <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                丢弃
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  if (
                    hasDanger &&
                    !window.confirm(
                      "本次修改包含标记为「关键」的配置项，确定继续保存？",
                    )
                  ) {
                    return;
                  }
                  patchMut.mutate(dirty);
                }}
                disabled={patchMut.isPending}
              >
                {patchMut.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                保存 {dirtyCount} 项
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── diff 表格 ──────────────────────────────────────────

function DiffTable({
  dirty,
  items,
  before,
  after,
}: {
  dirty: Record<string, ConfigValue>;
  items: Record<string, ConfigItemMeta>;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-border/40 text-xs text-muted-foreground">
          <tr className="text-left">
            <th className="px-3 py-2 font-medium">配置项</th>
            <th className="px-3 py-2 font-medium">当前</th>
            <th className="px-3 py-2 font-medium">→</th>
            <th className="px-3 py-2 font-medium">新</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {Object.keys(dirty).map((k) => {
            const m = items[k];
            const b = getByPath(before, k);
            const a = getByPath(after, k);
            return (
              <tr key={k}>
                <td className="px-3 py-2">
                  <div className="text-sm">{m?.label ?? k}</div>
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {k}
                  </div>
                </td>
                <td className="px-3 py-2 font-mono num text-xs text-muted-foreground">
                  {m ? formatForDisplay(b as ConfigValue, m) : String(b)}
                </td>
                <td className="px-2 text-center text-muted-foreground">→</td>
                <td className="px-3 py-2 font-mono num text-xs text-primary">
                  {m ? formatForDisplay(a as ConfigValue, m) : String(a)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-12">
      <div className="lg:col-span-3">
        <Skeleton className="h-96 w-full" />
      </div>
      <div className="lg:col-span-9 space-y-3">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    </div>
  );
}

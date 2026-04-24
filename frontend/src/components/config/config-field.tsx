import { AlertTriangle, HelpCircle, RotateCcw } from "lucide-react";

import type { ConfigItemMeta, ConfigValue } from "@/lib/types";
import { formatForDisplay } from "@/lib/config-utils";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

interface Props {
  keyPath: string;
  meta: ConfigItemMeta;
  value: ConfigValue;
  defaultValue: ConfigValue;
  isOverridden: boolean;
  isDirty: boolean;
  onChange: (v: ConfigValue) => void;
  onReset?: () => void;
}

export function ConfigField({
  keyPath,
  meta,
  value,
  defaultValue,
  isOverridden,
  isDirty,
  onChange,
  onReset,
}: Props) {
  const danger = !!meta.danger;

  return (
    <div
      className={cn(
        "space-y-1.5 rounded-md border px-3 py-2.5 transition-colors",
        isDirty
          ? "border-primary/60 bg-primary/5"
          : isOverridden
            ? "border-warning/40 bg-warning/5"
            : "border-border/40 bg-background/40",
      )}
    >
      {/* 行头：label + 徽标 + 操作 */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm font-medium">{meta.label}</span>
          {danger && (
            <Badge variant="destructive" className="gap-1 font-normal">
              <AlertTriangle className="h-3 w-3" />
              关键
            </Badge>
          )}
          {isDirty ? (
            <Badge variant="default" className="font-normal">
              未保存
            </Badge>
          ) : isOverridden ? (
            <Badge variant="warning" className="font-normal">
              已覆盖
            </Badge>
          ) : null}
          {meta.help && (
            <span
              className="group relative inline-flex items-center"
              title={meta.help}
            >
              <HelpCircle className="h-3.5 w-3.5 text-muted-foreground/70" />
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {isOverridden && onReset && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-xs"
              onClick={onReset}
              title="重置为默认值"
            >
              <RotateCcw className="mr-1 h-3 w-3" />
              重置
            </Button>
          )}
        </div>
      </div>

      {/* 字段主体 */}
      <div>
        <Control meta={meta} value={value} onChange={onChange} />
      </div>

      {/* 辅助信息 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
        <span className="font-mono">{keyPath}</span>
        <span>·</span>
        <span>
          默认 <span className="text-foreground/70">{formatForDisplay(defaultValue, meta)}</span>
        </span>
        {meta.impact && (
          <>
            <span>·</span>
            <span className="italic">{meta.impact}</span>
          </>
        )}
      </div>
    </div>
  );
}

// ─── 控件本体：按 type 分发 ─────────────────────────────

function Control({
  meta,
  value,
  onChange,
}: {
  meta: ConfigItemMeta;
  value: ConfigValue;
  onChange: (v: ConfigValue) => void;
}) {
  const t = meta.type;

  if (t === "bool") {
    return (
      <div className="flex items-center gap-2">
        <Switch
          checked={Boolean(value)}
          onCheckedChange={(b) => onChange(b)}
        />
        <span className="text-sm text-muted-foreground">
          {value ? "开启" : "关闭"}
        </span>
      </div>
    );
  }

  if (t === "enum") {
    const opts = meta.options ?? [];
    return (
      <Select
        value={String(value)}
        onValueChange={(v) => {
          // 尝试还原数字选项
          const found = opts.find((o) => String(o) === v);
          onChange(typeof found === "number" ? found : v);
        }}
      >
        <SelectTrigger className="h-8 w-48">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {opts.map((o) => (
            <SelectItem key={String(o)} value={String(o)}>
              {String(o)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (t === "percent") {
    // 0~1 浮点 → 滑条 + 百分比显示
    return (
      <NumberSlider
        value={Number(value)}
        min={meta.min ?? 0}
        max={meta.max ?? 1}
        step={meta.step ?? 0.01}
        onChange={onChange}
        format={(n) => `${(n * 100).toFixed(2)}%`}
      />
    );
  }

  if (t === "weight") {
    return (
      <NumberSlider
        value={Number(value)}
        min={meta.min ?? 0}
        max={meta.max ?? 1}
        step={meta.step ?? 0.05}
        onChange={onChange}
        format={(n) => n.toFixed(2)}
      />
    );
  }

  if (t === "int" || t === "number") {
    return (
      <Input
        type="number"
        className="h-8 w-40 font-mono num"
        value={String(value ?? "")}
        step={meta.step ?? (t === "int" ? 1 : 0.1)}
        min={meta.min}
        max={meta.max}
        onChange={(e) => {
          const n = e.target.value === "" ? 0 : Number(e.target.value);
          if (!Number.isFinite(n)) return;
          onChange(t === "int" ? Math.round(n) : n);
        }}
      />
    );
  }

  if (t === "array") {
    const it = meta.item_type ?? "number";
    const text = Array.isArray(value) ? value.join(", ") : "";
    return (
      <Input
        className="h-8 w-full font-mono text-xs"
        value={text}
        placeholder={it === "number" ? "1.5, 2.5, 3.5" : "a, b, c"}
        onChange={(e) => {
          const arr = e.target.value
            .split(",")
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
            .map((s) => (it === "number" ? Number(s) : s));
          // 过滤非法数字项
          if (it === "number" && (arr as number[]).some((n) => !Number.isFinite(n)))
            return;
          onChange(arr as number[] | string[]);
        }}
      />
    );
  }

  // string fallback
  return (
    <Input
      className="h-8 w-full"
      value={String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

// ─── 数字滑条（percent / weight 用） ──────────────────

function NumberSlider({
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format: (n: number) => string;
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(value) ? value : min}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <Input
        type="number"
        className="h-8 w-24 font-mono num"
        value={Number.isFinite(value) ? value : ""}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isFinite(n)) return;
          onChange(n);
        }}
      />
      <span className="w-16 shrink-0 text-right font-mono num text-xs text-muted-foreground">
        {format(Number(value))}
      </span>
    </div>
  );
}

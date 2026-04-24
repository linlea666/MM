import { useMemo, useState } from "react";
import type { Level, LevelLadder } from "@/lib/types";
import { cn, formatPrice, formatPct } from "@/lib/utils";
import { fitColor, fitLabel, strengthLabel } from "@/lib/ui-helpers";

type TabKey = "all" | "support" | "resistance";
type DistanceKey = "near" | "mid" | "far";

interface RowData {
  label: string; // R1 / R2 / R3 / S1 / S2 / S3
  level: Level;
  side: "support" | "resistance";
  gapPct: number; // 相对当前价，带符号
  absGap: number;
  distance: DistanceKey;
}

const DISTANCE_RANGES: Record<DistanceKey, { label: string; hint: string; min: number; max: number }> = {
  near: { label: "近距", hint: "0.25–1.5%", min: 0, max: 1.5 },
  mid: { label: "中距", hint: "1.5–4%", min: 1.5, max: 4 },
  far: { label: "远距", hint: "4–12%", min: 4, max: 12 },
};

function classifyDistance(absGap: number): DistanceKey {
  if (absGap < 1.5) return "near";
  if (absGap < 4) return "mid";
  return "far";
}

interface Props {
  ladder: LevelLadder;
  /** 优先使用实时价 */
  livePrice?: number | null;
}

export function KeyLevelsTabs({ ladder, livePrice }: Props) {
  const [tab, setTab] = useState<TabKey>("all");
  const [distance, setDistance] = useState<DistanceKey | "all">("all");

  const current = livePrice ?? ladder.current_price;

  const rows = useMemo<RowData[]>(() => {
    const make = (lv: Level | null | undefined, label: string, side: "support" | "resistance"): RowData | null => {
      if (!lv) return null;
      const gapPct = ((lv.price - current) / current) * 100;
      const absGap = Math.abs(gapPct);
      return {
        label,
        level: lv,
        side,
        gapPct,
        absGap,
        distance: classifyDistance(absGap),
      };
    };
    const list: RowData[] = [];
    const candidates = [
      make(ladder.r1, "R1", "resistance"),
      make(ladder.r2, "R2", "resistance"),
      make(ladder.r3, "R3", "resistance"),
      make(ladder.s1, "S1", "support"),
      make(ladder.s2, "S2", "support"),
      make(ladder.s3, "S3", "support"),
    ];
    for (const row of candidates) if (row) list.push(row);
    // 按距当前价由近到远排序
    list.sort((a, b) => a.absGap - b.absGap);
    return list;
  }, [ladder, current]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (tab === "support" && r.side !== "support") return false;
      if (tab === "resistance" && r.side !== "resistance") return false;
      if (distance !== "all" && r.distance !== distance) return false;
      return true;
    });
  }, [rows, tab, distance]);

  const supportCount = rows.filter((r) => r.side === "support").length;
  const resistanceCount = rows.filter((r) => r.side === "resistance").length;

  return (
    <div className="panel-glass rounded-lg">
      <div className="flex items-center justify-between p-4 pb-3">
        <div>
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            关键位明细
          </div>
          <div className="mt-0.5 text-sm font-semibold">
            按距离排序 · 共 {rows.length} 个
          </div>
        </div>

        {/* Tab: 全部 / 支撑 / 阻力 */}
        <div className="flex items-center gap-1 rounded-md border border-border/50 bg-background/50 p-0.5">
          <TabBtn active={tab === "all"} onClick={() => setTab("all")}>
            全部 <span className="opacity-60">· {rows.length}</span>
          </TabBtn>
          <TabBtn
            active={tab === "support"}
            color="lime"
            onClick={() => setTab("support")}
          >
            强支撑 <span className="opacity-60">· {supportCount}</span>
          </TabBtn>
          <TabBtn
            active={tab === "resistance"}
            color="magenta"
            onClick={() => setTab("resistance")}
          >
            强阻力 <span className="opacity-60">· {resistanceCount}</span>
          </TabBtn>
        </div>
      </div>

      {/* 距离过滤 */}
      <div className="flex items-center gap-2 border-y border-border/30 bg-background/30 px-4 py-2 text-xs">
        <span className="text-muted-foreground">距离筛选：</span>
        <DistChip active={distance === "all"} onClick={() => setDistance("all")}>
          全部
        </DistChip>
        {(Object.keys(DISTANCE_RANGES) as DistanceKey[]).map((k) => (
          <DistChip
            key={k}
            active={distance === k}
            onClick={() => setDistance(k)}
          >
            {DISTANCE_RANGES[k].label}{" "}
            <span className="opacity-60">{DISTANCE_RANGES[k].hint}</span>
          </DistChip>
        ))}
      </div>

      {/* 列表 */}
      <div className="max-h-[480px] overflow-y-auto p-3 scrollbar-thin">
        {filtered.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            当前筛选下无关键位
          </div>
        ) : (
          <div className="space-y-2.5">
            {filtered.map((r) => (
              <LevelDetailCard key={r.label} row={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 子组件 ─────────────────────────────────────

function TabBtn({
  active,
  color,
  onClick,
  children,
}: {
  active: boolean;
  color?: "lime" | "magenta";
  onClick: () => void;
  children: React.ReactNode;
}) {
  const activeCls =
    color === "lime"
      ? "bg-neon-lime/15 text-neon-lime"
      : color === "magenta"
      ? "bg-neon-magenta/15 text-neon-magenta"
      : "bg-neon-cyan/15 text-neon-cyan";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded px-2.5 py-1 text-xs font-medium transition-colors",
        active ? activeCls : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function DistChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded border px-2 py-0.5 text-[11px] transition-colors",
        active
          ? "border-neon-cyan/60 bg-neon-cyan/10 text-neon-cyan"
          : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function LevelDetailCard({ row }: { row: RowData }) {
  const isRes = row.side === "resistance";
  const sideColor = isRes ? "magenta" : "lime";
  const stars = Math.max(1, Math.min(5, Math.round((row.level.score ?? 0) / 20)));

  // 历史验证文案
  const historyText = (() => {
    if (row.level.test_count === 0) return "暂未被价格触碰（干净位）";
    const tc = row.level.test_count;
    const parts: string[] = [];
    if (row.level.fit === "first_test_good") {
      parts.push(`被测试 ${tc} 次 · 首次机会仍在`);
    } else if (row.level.fit === "worn_out") {
      parts.push(`被测试 ${tc} 次 · 磨损严重`);
    } else if (row.level.fit === "can_break") {
      parts.push(`被测试 ${tc} 次 · 已被削弱`);
    } else {
      parts.push(`被测试 ${tc} 次`);
    }
    if (row.level.decay_pct > 0.1) {
      parts.push(`已衰减 ${(row.level.decay_pct * 100).toFixed(0)}%`);
    }
    return parts.join(" · ");
  })();

  // 当前状态 → 人话
  const stateLine = (() => {
    if (row.level.fit === "first_test_good") {
      return isRes ? "首次测试 · 该位有反弹概率" : "首次测试 · 该位有承接概率";
    }
    if (row.level.fit === "worn_out") {
      return "反复测试已磨损 · 反弹/承接力度减弱";
    }
    if (row.level.fit === "can_break") {
      return isRes ? "墙已变薄 · 可能快速击穿" : "底已变薄 · 可能跌破";
    }
    return "暂无明确信号 · 观望";
  })();

  return (
    <div
      className={cn(
        "rounded-md border bg-background/50 p-3 transition-colors",
        isRes
          ? "border-neon-magenta/30 accent-stripe-magenta"
          : "border-neon-lime/30 accent-stripe-lime",
      )}
    >
      {/* 第一行：距离徽章 + 价格 + 涨跌幅 + 强度星 */}
      <div className="flex items-center gap-2.5">
        <span className={cn("chip", `chip-${sideColor}`)}>
          {row.distance === "near" ? "近距" : row.distance === "mid" ? "中距" : "远距"}
        </span>
        <div className="flex-1">
          <span
            className={cn(
              "num text-lg font-bold",
              isRes ? "text-neon-magenta glow-magenta" : "text-neon-lime glow-lime",
            )}
          >
            {formatPrice(row.level.price)}
          </span>
          <span
            className={cn(
              "ml-2 num text-xs",
              row.gapPct >= 0 ? "text-neon-magenta/80" : "text-neon-lime/80",
            )}
          >
            {row.gapPct >= 0 ? "+" : ""}
            {formatPct(row.gapPct)}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {Array.from({ length: 5 }).map((_, i) => (
            <span
              key={i}
              className={cn(
                "text-sm",
                i < stars
                  ? isRes
                    ? "text-neon-magenta"
                    : "text-neon-lime"
                  : "text-muted-foreground/30",
              )}
            >
              ★
            </span>
          ))}
          <span className="chip ml-2">{row.label}</span>
        </div>
      </div>

      {/* 为什么入选 */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="text-muted-foreground">为什么入选：</span>
        {row.level.sources.map((s) => (
          <span key={s} className="chip chip-cyan">
            {humanizeSource(s)}
          </span>
        ))}
      </div>

      {/* 历史验证 */}
      <div className="mt-1.5 flex items-start gap-2 text-[11px]">
        <span className="shrink-0 text-muted-foreground">历史验证：</span>
        <span className="text-foreground/85">{historyText}</span>
      </div>

      {/* 当前状态 */}
      <div className="mt-1.5 flex items-center gap-2 text-[11px]">
        <span className="shrink-0 text-muted-foreground">当前状态：</span>
        <span className={cn("font-medium", fitColor(row.level.fit))}>
          {fitLabel(row.level.fit)}
        </span>
        <span className="opacity-40">·</span>
        <span className="text-foreground/75">{stateLine}</span>
      </div>

      {/* 底部：强度 + 与当前价相比 */}
      <div className="mt-2 flex items-center justify-between border-t border-border/30 pt-2 text-[11px]">
        <span className="text-muted-foreground">
          强度：<span className="text-foreground/85">{strengthLabel(row.level.strength)}</span>
        </span>
        <span className="text-muted-foreground">
          与当前价相比：
          <span
            className={cn(
              "num ml-1 font-medium",
              row.gapPct >= 0 ? "text-neon-magenta" : "text-neon-lime",
            )}
          >
            {row.gapPct >= 0 ? "↑ 上方" : "↓ 下方"} {formatPct(Math.abs(row.gapPct))}
          </span>
        </span>
      </div>
    </div>
  );
}

// HFD 内部英文指标 → 人话
function humanizeSource(source: string): string {
  const map: Record<string, string> = {
    trend_cost: "趋势成本带",
    trend_price: "趋势撑压",
    smart_money_cost: "主力成本",
    absolute_zones: "密集博弈区",
    fvg: "筹码真空区",
    micro_poc: "微观 POC",
    hvn: "高成交节点",
    liq_heatmap: "清算痛点",
    liquidation_heatmap: "清算痛点",
    liquidation_fuel: "清算燃料",
    liquidity_sweep: "猎杀目标",
    inst_volume_profile: "筹码分布",
    poc_shift: "成本位移",
    ob_decay: "订单墙",
  };
  return map[source] ?? source;
}

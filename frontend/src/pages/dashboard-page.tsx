import { useState } from "react";
import { useSymbolStore } from "@/stores/symbol-store";
import { useDashboardStream } from "@/hooks/use-dashboard-stream";
import { useLivePrice } from "@/hooks/use-live-price";
import { HeroVerdict } from "@/components/dashboard/hero-verdict";
import { KeySpaceMap } from "@/components/dashboard/key-space-map";
import { KeyLevelsTabs } from "@/components/dashboard/key-levels-tabs";
import { ActionTriggers } from "@/components/dashboard/action-triggers";
import {
  MainForceCompact,
  PhaseCompact,
  LiquidityCompact,
} from "@/components/dashboard/compact-cards";
import { ChochCard } from "@/components/dashboard/choch-card";
import { LiquidationBandsCard } from "@/components/dashboard/liquidation-bands-card";
import { RetailBandsCard } from "@/components/dashboard/retail-bands-card";
import { SegmentPortraitCard } from "@/components/dashboard/segment-portrait-card";
import { MomentumPulseCardView } from "@/components/dashboard/momentum-pulse";
import { TargetProjectionCardView } from "@/components/dashboard/target-projection";
import { TimelineCard } from "@/components/dashboard/timeline-card";
import { CapabilityScoresInline } from "@/components/dashboard/capability-scores-inline";
import { DashboardSkeleton } from "@/components/dashboard/dashboard-skeleton";
import { DashboardError } from "@/components/dashboard/dashboard-error";
import { ConnectionIndicator } from "@/components/dashboard/connection-indicator";
import { RecentReportsCard } from "@/components/dashboard/recent-reports-card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";

export default function DashboardPage() {
  const symbol = useSymbolStore((s) => s.symbol);
  const tf = useSymbolStore((s) => s.tf);

  const stream = useDashboardStream(symbol, tf);
  const live = useLivePrice(symbol);
  const [capExpanded, setCapExpanded] = useState(false);

  if (stream.isLoading && !stream.data) {
    return <DashboardSkeleton />;
  }

  if (stream.isError && !stream.data) {
    return (
      <DashboardError
        error={stream.error as Error}
        onRetry={() => stream.refetch()}
        symbol={symbol}
        tf={tf}
      />
    );
  }

  const snap = stream.data!;

  return (
    <div className="grid gap-4">
      {/* 行 1：结论带（实时价 + 一句话结论 + 策略建议） */}
      <HeroVerdict snap={snap} />

      {/* 数据不新鲜提醒 */}
      {!snap.health.fresh && (
        <Badge variant="warning" className="gap-1.5 px-3 py-1">
          <AlertTriangle className="h-3.5 w-3.5" />
          数据不新鲜
          {snap.health.stale_seconds !== null &&
            snap.health.stale_seconds !== undefined && (
              <>
                （滞后 <span className="num">{snap.health.stale_seconds}s</span>）
              </>
            )}
          {snap.health.warnings.length > 0 && (
            <span className="ml-2 opacity-80">
              · {snap.health.warnings.slice(0, 2).join(" / ")}
            </span>
          )}
        </Badge>
      )}

      {/* 行 2：决策三驾马车 —— 空间图 + 关键位明细 + 触发条件 */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <KeySpaceMap ladder={snap.levels} livePrice={live.price} />
        </div>
        <div className="lg:col-span-5">
          <KeyLevelsTabs ladder={snap.levels} livePrice={live.price} />
        </div>
        <div className="lg:col-span-3">
          <ActionTriggers snap={snap} />
        </div>
      </div>

      {/* 行 2.4：V1.1 · Step 7 · 动能能量柱 + 目标投影（磁吸地图） */}
      {snap.cards && (
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <MomentumPulseCardView
              card={snap.cards.momentum_pulse}
              tf={tf}
              anchorTs={snap.timestamp}
            />
          </div>
          <div className="lg:col-span-7">
            <TargetProjectionCardView
              card={snap.cards.target_projection}
              livePrice={live.price ?? snap.current_price}
            />
          </div>
        </div>
      )}

      {/* 行 2.5：V1.1 数字化观察 —— ⚡ CHoCH / 💣 爆仓带 / 散户止损 / 波段四维 */}
      {snap.cards && (
        <div className="grid gap-4 lg:grid-cols-12">
          <div className="lg:col-span-3">
            <ChochCard card={snap.cards.choch_latest} />
          </div>
          <div className="lg:col-span-3">
            <LiquidationBandsCard
              longFuel={snap.cards.cascade_long_fuel}
              shortFuel={snap.cards.cascade_short_fuel}
            />
          </div>
          <div className="lg:col-span-3">
            <RetailBandsCard
              longFuel={snap.cards.retail_long_fuel}
              shortFuel={snap.cards.retail_short_fuel}
            />
          </div>
          <div className="lg:col-span-3">
            <SegmentPortraitCard card={snap.cards.segment} />
          </div>
        </div>
      )}

      {/* 行 3：三张浓缩卡（说人话） */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <MainForceCompact
            behavior={snap.behavior}
            participation={snap.participation}
          />
        </div>
        <div className="lg:col-span-4">
          <PhaseCompact phase={snap.phase} />
        </div>
        <div className="lg:col-span-4">
          <LiquidityCompact liquidity={snap.liquidity} />
        </div>
      </div>

      {/* 行 4：近期异动（全宽） */}
      <TimelineCard events={snap.recent_events} />

      {/* 行 4.5：最近 10 条 AI 深度分析报告 */}
      <RecentReportsCard />

      {/* 行 5：六大能力评分（默认折叠） */}
      <div className="panel-glass rounded-lg">
        <button
          type="button"
          onClick={() => setCapExpanded((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-white/5"
        >
          <div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              深度数据
            </div>
            <div className="mt-0.5 text-sm font-semibold">
              六大能力评分（调参/复盘用）
            </div>
          </div>
          {capExpanded ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
        {capExpanded && (
          <div className="border-t border-border/30 p-4">
            <CapabilityScoresInline scores={snap.capability_scores} />
          </div>
        )}
      </div>

      {/* 底部连接/刷新状态 */}
      <ConnectionIndicator
        wsStatus={stream.wsStatus}
        wsLive={stream.wsLive}
        lastSnapshotAt={stream.lastSnapshotAt}
        source={stream.source}
        onRefresh={() => stream.refetch()}
      />
    </div>
  );
}

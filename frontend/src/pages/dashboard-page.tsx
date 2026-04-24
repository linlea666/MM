import { useSymbolStore } from "@/stores/symbol-store";
import { useDashboardStream } from "@/hooks/use-dashboard-stream";
import { HeroStrip } from "@/components/dashboard/hero-strip";
import { MainForceRadar } from "@/components/dashboard/main-force-radar";
import { PhaseStateCard } from "@/components/dashboard/phase-state";
import { ParticipationCard } from "@/components/dashboard/participation-gate";
import { KeyLevelsLadder } from "@/components/dashboard/key-levels-ladder";
import { LiquidityCompassCard } from "@/components/dashboard/liquidity-compass";
import { TradePlansCard } from "@/components/dashboard/trade-plans";
import { TimelineCard } from "@/components/dashboard/timeline-card";
import { CapabilityScoresCard } from "@/components/dashboard/capability-scores-card";
import { DashboardSkeleton } from "@/components/dashboard/dashboard-skeleton";
import { DashboardError } from "@/components/dashboard/dashboard-error";
import { ConnectionIndicator } from "@/components/dashboard/connection-indicator";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle } from "lucide-react";

export default function DashboardPage() {
  const symbol = useSymbolStore((s) => s.symbol);
  const tf = useSymbolStore((s) => s.tf);

  const stream = useDashboardStream(symbol, tf);

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
      <HeroStrip snap={snap} />

      {/* Health 提示 */}
      {!snap.health.fresh && (
        <Badge variant="warning" className="gap-1.5 px-3 py-1">
          <AlertTriangle className="h-3.5 w-3.5" />
          数据不新鲜
          {snap.health.stale_seconds !== null &&
            snap.health.stale_seconds !== undefined && (
              <>
                （滞后 <span className="font-mono num">{snap.health.stale_seconds}s</span>）
              </>
            )}
          {snap.health.warnings.length > 0 && (
            <span className="ml-2 opacity-80">
              · {snap.health.warnings.slice(0, 2).join(" / ")}
            </span>
          )}
        </Badge>
      )}

      {/* 第二行：雷达(6) / 阶段(3) / 参与(3) */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-6">
          <MainForceRadar behavior={snap.behavior} />
        </div>
        <div className="lg:col-span-3">
          <PhaseStateCard phase={snap.phase} />
        </div>
        <div className="lg:col-span-3">
          <ParticipationCard gate={snap.participation} />
        </div>
      </div>

      {/* 第三行：关键位(6) / 流动性(6) */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-6">
          <KeyLevelsLadder ladder={snap.levels} />
        </div>
        <div className="lg:col-span-6">
          <LiquidityCompassCard liquidity={snap.liquidity} />
        </div>
      </div>

      {/* 第四行：计划(8) / Timeline(4) */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <TradePlansCard plans={snap.plans} />
        </div>
        <div className="lg:col-span-4">
          <TimelineCard events={snap.recent_events} />
        </div>
      </div>

      {/* 第五行：能力评分 */}
      <CapabilityScoresCard scores={snap.capability_scores} />

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

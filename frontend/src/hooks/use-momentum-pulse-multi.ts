import { useQuery } from "@tanstack/react-query";

import { fetchMomentumPulseMulti } from "@/lib/api";
import type { MomentumPulseMultiResp } from "@/lib/types";

/**
 * V1.1 · Step 7 · 多 TF 动能能量柱 + 目标投影
 *
 * 行为：
 * 1. 5 秒 polling（与后端 dashboard_cache TTL=2s 对齐，留余量；K 线 +5s 时也能拿到新数据）
 * 2. tf 列表为单一真源 30m / 1h / 4h（与后端 SUPPORTED_TFS 一致）
 * 3. 不接 WS（后端 WS 仅推主 dashboard，多 TF 灯带是辅助视图，5s polling 足够）
 *
 * 调用方：MomentumPulseCard 顶部三色灯带 + TargetProjectionCard 顶部 TF 切换器。
 */

const DEFAULT_TFS = ["30m", "1h", "4h"] as const;

export interface MomentumPulseMultiState {
  data: MomentumPulseMultiResp | undefined;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useMomentumPulseMulti(
  symbol: string,
  tfs: readonly string[] = DEFAULT_TFS,
): MomentumPulseMultiState {
  const tfsKey = tfs.join(",");
  const query = useQuery<MomentumPulseMultiResp, Error>({
    queryKey: ["momentum_pulse_multi", symbol, tfsKey],
    queryFn: () =>
      fetchMomentumPulseMulti({ symbol, tfs: Array.from(tfs) }),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    staleTime: 2_000,
    retry: (count) => count < 1,
  });

  return {
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: () => query.refetch(),
  };
}

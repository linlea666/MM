import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchDashboard } from "@/lib/api";
import { WsClient, type WsStatus } from "@/lib/ws";
import type { DashboardSnapshot, WsDashboardMsg } from "@/lib/types";

export interface DashboardStreamState {
  data: DashboardSnapshot | undefined;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
  /** WS 当前连接状态 */
  wsStatus: WsStatus;
  /** 本会话是否已至少收到过 1 条 WS snapshot（作为"实时可用"标志） */
  wsLive: boolean;
  /** 最近一次 WS snapshot 到达时间（ms epoch） */
  lastSnapshotAt: number | null;
  /** 数据来源最后一次更新的来源标签 */
  source: "ws" | "rest" | null;
}

/**
 * Dashboard 数据流：REST 初始化 + WS 实时推送。
 *
 * 工作方式：
 *  1. 挂载时立刻用 REST 取一次（保证首屏秒开 + 作为 WS 未达时的兜底）。
 *  2. 同步建立 WS，订阅 {symbol, tf}。WS `snapshot` 帧到达后写入 react-query cache。
 *  3. WS 已 live（收到过 snapshot） → 暂停 REST 轮询；WS 断线或尚未 live → 5s 轮询兜底。
 *  4. symbol / tf 变化 → 关闭旧 WS，重新 REST + 重新 subscribe（避免脏数据）。
 */
export function useDashboardStream(
  symbol: string,
  tf: string,
): DashboardStreamState {
  const qc = useQueryClient();
  const [wsStatus, setWsStatus] = useState<WsStatus>("closed");
  const [wsLive, setWsLive] = useState(false);
  const [lastSnapshotAt, setLastSnapshotAt] = useState<number | null>(null);
  const [source, setSource] = useState<"ws" | "rest" | null>(null);

  // REST 查询：WS live 期间关闭轮询，断线/未就绪时 5s 兜底
  const query = useQuery<DashboardSnapshot, Error>({
    queryKey: ["dashboard", symbol, tf],
    queryFn: async () => {
      const d = await fetchDashboard({ symbol, tf });
      setSource((prev) => (prev === "ws" ? "ws" : "rest"));
      return d;
    },
    refetchInterval: wsLive ? false : 5_000,
    refetchIntervalInBackground: false,
    staleTime: 2_000,
    retry: (count, err) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) return false;
      return count < 1;
    },
  });

  // WS 生命周期：依赖 symbol / tf；变化时销毁重建
  const clientRef = useRef<WsClient<WsDashboardMsg> | null>(null);
  useEffect(() => {
    setWsLive(false);
    const frame = { action: "subscribe", symbol, tf };
    const client = new WsClient<WsDashboardMsg>({
      path: "/ws/dashboard",
      subscribeFrame: frame,
      onStatus: (s) => {
        setWsStatus(s);
        if (s !== "open") {
          // 连接断开 → 不能再视为 live，回退到 REST 轮询
          setWsLive(false);
        }
      },
      onMessage: (msg) => {
        if (msg.type === "snapshot") {
          // 只接受匹配当前订阅的 snapshot（切换瞬间可能有残留）
          if (msg.symbol !== symbol || msg.tf !== tf) return;
          qc.setQueryData(["dashboard", symbol, tf], msg.data);
          setWsLive(true);
          setLastSnapshotAt(Date.now());
          setSource("ws");
        } else if (msg.type === "error") {
          // NO_DATA / NO_ACTIVE_SUBSCRIPTION：保持 REST 兜底路径
          setWsLive(false);
        }
      },
    });
    clientRef.current = client;
    client.connect();
    return () => {
      client.close();
      clientRef.current = null;
    };
  }, [symbol, tf, qc]);

  return {
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: (query.error as Error) ?? null,
    refetch: () => {
      void query.refetch();
    },
    wsStatus,
    wsLive,
    lastSnapshotAt,
    source,
  };
}

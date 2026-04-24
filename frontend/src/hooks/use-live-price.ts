import { useEffect, useRef, useState } from "react";

/**
 * 币安现货 miniTicker 实时价。
 *
 * 设计要点：
 * 1. WS 直连 `wss://stream.binance.com:9443/ws/{symbol}usdt@miniTicker`
 *    —— 不经过后端，减少 1 跳延迟；后端挂掉也不影响价格显示
 * 2. 单连接，切 symbol 时优雅关闭旧连接
 * 3. 网络异常 → 指数退避重连（1s / 2s / 4s / 8s / 16s 封顶）
 * 4. 同时返回 24h 涨跌幅（LIQ 风格的 Hero 带用）
 * 5. 返回 `null` 时调用方应 fallback 到 snapshot.current_price
 */

export interface LivePriceState {
  /** 最新成交价 */
  price: number | null;
  /** 24h 涨跌幅（百分比，如 -1.23 表示 -1.23%） */
  change24h: number | null;
  /** 24h 最高 */
  high24h: number | null;
  /** 24h 最低 */
  low24h: number | null;
  /** 最后更新时间（本地 ms） */
  updatedAt: number | null;
  /** WS 连接状态 */
  status: "connecting" | "open" | "closed" | "error";
}

interface BinanceMiniTicker {
  e: string; // 事件类型 '24hrMiniTicker'
  E: number; // 事件时间
  s: string; // 交易对
  c: string; // 最新价
  o: string; // 开盘价（24h 前）
  h: string; // 最高价
  l: string; // 最低价
  v: string; // 成交量（基础资产）
  q: string; // 成交量（计价资产）
}

function pctChange(last: number, open: number): number {
  if (open <= 0) return 0;
  return ((last - open) / open) * 100;
}

export function useLivePrice(symbol: string | null | undefined): LivePriceState {
  const [state, setState] = useState<LivePriceState>({
    price: null,
    change24h: null,
    high24h: null,
    low24h: null,
    updatedAt: null,
    status: "connecting",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef(1000);
  const manualCloseRef = useRef(false);

  useEffect(() => {
    if (!symbol) return;

    const pair = `${symbol.toLowerCase()}usdt`;
    const url = `wss://stream.binance.com:9443/ws/${pair}@miniTicker`;
    manualCloseRef.current = false;

    const connect = () => {
      setState((s) => ({ ...s, status: "connecting" }));
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        backoffRef.current = 1000;
        setState((s) => ({ ...s, status: "open" }));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as BinanceMiniTicker;
          const last = Number(msg.c);
          const open = Number(msg.o);
          const high = Number(msg.h);
          const low = Number(msg.l);
          if (!Number.isFinite(last)) return;
          setState({
            price: last,
            change24h: Number.isFinite(open) ? pctChange(last, open) : null,
            high24h: Number.isFinite(high) ? high : null,
            low24h: Number.isFinite(low) ? low : null,
            updatedAt: Date.now(),
            status: "open",
          });
        } catch {
          // 忽略格式异常
        }
      };

      ws.onerror = () => {
        setState((s) => ({ ...s, status: "error" }));
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (manualCloseRef.current) return;
        setState((s) => ({ ...s, status: "closed" }));
        // 指数退避重连
        const delay = Math.min(backoffRef.current, 16_000);
        reconnectTimerRef.current = setTimeout(connect, delay);
        backoffRef.current = Math.min(backoffRef.current * 2, 16_000);
      };
    };

    connect();

    return () => {
      manualCloseRef.current = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* ignore */
        }
        wsRef.current = null;
      }
      // 切 symbol 时重置到未知状态
      setState({
        price: null,
        change24h: null,
        high24h: null,
        low24h: null,
        updatedAt: null,
        status: "connecting",
      });
    };
  }, [symbol]);

  return state;
}

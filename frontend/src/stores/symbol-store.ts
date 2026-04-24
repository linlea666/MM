import { create } from "zustand";
import { persist, type PersistStorage } from "zustand/middleware";

/**
 * V1.1 · 周期单一真源：前后端只认 30m / 1h / 4h。
 *
 * 历史版本曾允许 5m/15m/2h/1d，但后端 `collector.timeframes` 只采这三档，
 * 会导致"前端发得出、后端空跑"的静默错误。这里把类型收紧到三档，并在
 * persist 层通过 `version=2 + migrate` 把老 localStorage 里的 5m/15m/2h/1d
 * 一次性降级到默认 30m（同时保留一次性 console.warn，便于用户察觉切换）。
 */
export type Tf = "30m" | "1h" | "4h";
export const ALLOWED_TFS: Tf[] = ["30m", "1h", "4h"];
export const DEFAULT_TF: Tf = "30m";

function isValidTf(v: unknown): v is Tf {
  return typeof v === "string" && (ALLOWED_TFS as string[]).includes(v);
}

interface SymbolState {
  symbol: string;
  tf: Tf;
  setSymbol: (s: string) => void;
  setTf: (t: Tf) => void;
}

/**
 * 老版本 persist 直接 `JSON.parse(localStorage)` → 塞回 state；升级 version
 * 到 2 时，zustand 会先走 migrate 把字段矫正，再应用到 store。
 */
const storage: PersistStorage<SymbolState> = {
  getItem: (name) => {
    const raw = localStorage.getItem(name);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },
  setItem: (name, value) => {
    localStorage.setItem(name, JSON.stringify(value));
  },
  removeItem: (name) => {
    localStorage.removeItem(name);
  },
};

export const useSymbolStore = create<SymbolState>()(
  persist(
    (set) => ({
      symbol: "BTC",
      tf: DEFAULT_TF,
      setSymbol: (s) => set({ symbol: s.trim().toUpperCase() }),
      setTf: (t) => set({ tf: isValidTf(t) ? t : DEFAULT_TF }),
    }),
    {
      name: "mm.symbol",
      version: 2,
      storage,
      migrate: (persistedState, fromVersion) => {
        // 任何低于 v2 的历史值（含原始 { symbol, tf } 无 version 的情况）
        // 统一做一次 tf 白名单校准。
        const prev = (persistedState ?? {}) as Partial<SymbolState>;
        const rawTf = prev.tf as unknown;
        const safeTf: Tf = isValidTf(rawTf) ? rawTf : DEFAULT_TF;
        if (fromVersion !== 2 && !isValidTf(rawTf) && rawTf !== undefined) {
          // 仅在确实发生降级时提醒一次，不淹没控制台
          // eslint-disable-next-line no-console
          console.warn(
            `[mm.symbol] 老版本 tf="${String(rawTf)}" 已不被支持（仅 30m/1h/4h），` +
              `自动回落到 ${DEFAULT_TF}。`,
          );
        }
        return {
          symbol: typeof prev.symbol === "string" ? prev.symbol : "BTC",
          tf: safeTf,
          setSymbol: () => undefined,
          setTf: () => undefined,
        } as SymbolState;
      },
    },
  ),
);

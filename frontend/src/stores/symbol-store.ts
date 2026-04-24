import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Tf = "5m" | "15m" | "30m" | "1h" | "2h" | "4h" | "1d";

interface SymbolState {
  symbol: string;
  tf: Tf;
  setSymbol: (s: string) => void;
  setTf: (t: Tf) => void;
}

export const useSymbolStore = create<SymbolState>()(
  persist(
    (set) => ({
      symbol: "BTC",
      tf: "30m",
      setSymbol: (s) => set({ symbol: s.trim().toUpperCase() }),
      setTf: (t) => set({ tf: t }),
    }),
    { name: "mm.symbol" },
  ),
);

export const ALLOWED_TFS: Tf[] = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"];

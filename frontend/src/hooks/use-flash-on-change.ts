import { useEffect, useRef, useState } from "react";

export type FlashDirection = "up" | "down" | null;

/**
 * 当数值发生变化时，短暂返回 "up" / "down" 作为闪烁方向，
 * 默认 800ms 后自动回落到 null。
 */
export function useFlashOnChange(
  value: number | null | undefined,
  durationMs = 800,
): FlashDirection {
  const prev = useRef<number | null | undefined>(value);
  const [dir, setDir] = useState<FlashDirection>(null);

  useEffect(() => {
    if (value === null || value === undefined) return;
    if (prev.current === null || prev.current === undefined) {
      prev.current = value;
      return;
    }
    if (value !== prev.current) {
      setDir(value > prev.current ? "up" : "down");
      prev.current = value;
      const t = window.setTimeout(() => setDir(null), durationMs);
      return () => window.clearTimeout(t);
    }
  }, [value, durationMs]);

  return dir;
}

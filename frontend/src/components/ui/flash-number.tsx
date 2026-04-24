import { useFlashOnChange } from "@/hooks/use-flash-on-change";
import { cn } from "@/lib/utils";

interface Props {
  value: number;
  format?: (v: number) => string;
  className?: string;
  /** 是否在闪烁时显示 ▲ / ▼ 小箭头（默认不显示，避免与价格争抢视线） */
  showArrow?: boolean;
  durationMs?: number;
}

/**
 * 数值变化时短暂闪烁：上升绿色、下降红色。
 * 适合用于实时价格、大数值展示。
 */
export function FlashNumber({
  value,
  format,
  className,
  showArrow = false,
  durationMs = 800,
}: Props) {
  const dir = useFlashOnChange(value, durationMs);

  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-1 transition-colors duration-500",
        dir === "up" && "text-bullish",
        dir === "down" && "text-bearish",
        className,
      )}
    >
      <span>{format ? format(value) : value}</span>
      {showArrow && dir === "up" && <span className="text-sm">▲</span>}
      {showArrow && dir === "down" && <span className="text-sm">▼</span>}
    </span>
  );
}

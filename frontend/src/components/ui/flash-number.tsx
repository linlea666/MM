import { useFlashOnChange } from "@/hooks/use-flash-on-change";
import { cn } from "@/lib/utils";

interface Props {
  value: number;
  format?: (v: number) => string;
  className?: string;
  /** 是否在闪烁时显示 ▲ / ▼ 小箭头（默认不显示，避免与价格争抢视线） */
  showArrow?: boolean;
  /**
   * 闪烁样式：
   *  - "bg"（默认）：短暂背景高亮，字色不变（适合 hero 发光价格）
   *  - "text"：直接用字色，覆盖 className 的 text-* 色
   */
  variant?: "bg" | "text";
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
  variant = "bg",
  durationMs = 800,
}: Props) {
  const dir = useFlashOnChange(value, durationMs);

  if (variant === "text") {
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

  // 背景高亮闪烁：不侵犯字色，字色由外层 className 决定
  return (
    <span
      className={cn(
        "inline-flex items-baseline gap-1 rounded px-1 -mx-1 transition-colors",
        dir === "up" && "animate-flash-up",
        dir === "down" && "animate-flash-down",
        className,
      )}
    >
      <span>{format ? format(value) : value}</span>
      {showArrow && dir === "up" && (
        <span className="text-sm text-neon-lime">▲</span>
      )}
      {showArrow && dir === "down" && (
        <span className="text-sm text-neon-magenta">▼</span>
      )}
    </span>
  );
}

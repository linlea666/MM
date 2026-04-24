import { Star } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  value: number; // 0~5
  size?: number;
  className?: string;
}

export function StarRating({ value, size = 14, className }: Props) {
  const v = Math.max(0, Math.min(5, Math.round(value)));
  return (
    <div className={cn("inline-flex items-center gap-0.5", className)}>
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          width={size}
          height={size}
          className={cn(
            "transition-colors",
            i < v
              ? "fill-warning text-warning"
              : "text-muted-foreground/40",
          )}
        />
      ))}
    </div>
  );
}

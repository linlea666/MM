import type {
  BehaviorMain,
  LevelFit,
  LevelStrength,
  ParticipationLevel,
  PhaseLabel,
  Severity,
  TradeAction,
} from "./types";

// ─── 颜色语义映射 ────────────────────────────────────

export function behaviorColor(main: BehaviorMain): string {
  switch (main) {
    case "强吸筹":
    case "弱吸筹":
      return "bg-bullish/20 text-bullish ring-1 ring-bullish/40";
    case "强派发":
    case "弱派发":
      return "bg-bearish/20 text-bearish ring-1 ring-bearish/40";
    case "趋势反转":
      return "bg-warning/20 text-warning ring-1 ring-warning/40";
    default:
      return "bg-muted text-muted-foreground ring-1 ring-border";
  }
}

export function phaseColor(label: PhaseLabel): string {
  switch (label) {
    case "真突破启动":
    case "趋势延续":
      return "bg-bullish/20 text-bullish ring-1 ring-bullish/40";
    case "假突破猎杀":
    case "趋势耗竭":
    case "黑洞加速":
      return "bg-bearish/20 text-bearish ring-1 ring-bearish/40";
    case "底部吸筹震荡":
    case "高位派发震荡":
      return "bg-warning/20 text-warning ring-1 ring-warning/40";
    default:
      return "bg-muted text-muted-foreground ring-1 ring-border";
  }
}

export function participationColor(l: ParticipationLevel): string {
  switch (l) {
    case "主力真参与":
      return "bg-bullish/20 text-bullish ring-1 ring-bullish/40";
    case "局部参与":
      return "bg-primary/20 text-primary ring-1 ring-primary/40";
    case "疑似散户":
      return "bg-warning/20 text-warning ring-1 ring-warning/40";
    case "垃圾时间":
      return "bg-muted text-muted-foreground ring-1 ring-border";
  }
}

export function strengthLabel(s: LevelStrength): string {
  return { strong: "强", medium: "中", weak: "弱" }[s];
}

export function strengthColor(s: LevelStrength): string {
  return {
    strong: "bg-primary/80 text-primary-foreground",
    medium: "bg-primary/40 text-foreground",
    weak: "bg-muted text-muted-foreground",
  }[s];
}

export function fitLabel(f: LevelFit): string {
  return {
    first_test_good: "首测机会",
    worn_out: "已磨损",
    can_break: "易击穿",
    observe: "观望",
  }[f];
}

export function fitColor(f: LevelFit): string {
  return {
    first_test_good: "text-bullish",
    worn_out: "text-muted-foreground",
    can_break: "text-bearish",
    observe: "text-foreground",
  }[f];
}

export function severityColor(s: Severity): string {
  return {
    info: "bg-secondary text-foreground",
    warning: "bg-warning/25 text-warning",
    alert: "bg-destructive/25 text-destructive",
  }[s];
}

export function actionColor(a: TradeAction): string {
  if (a === "追多" || a === "回踩做多") {
    return "text-bullish";
  }
  if (a === "追空" || a === "反弹做空") {
    return "text-bearish";
  }
  if (a === "反手") {
    return "text-warning";
  }
  return "text-muted-foreground";
}

// 分数 0~100 → tailwind indicator 色
export function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-bullish";
  if (score >= 40) return "bg-primary";
  if (score >= 20) return "bg-warning";
  return "bg-muted-foreground";
}

// ms 时间戳 → 相对时间（几秒 / 几分 / 几小时前）
export function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  if (diff < 0) return "刚刚";
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s 前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m 前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h 前`;
  const d = Math.floor(hr / 24);
  return `${d}d 前`;
}

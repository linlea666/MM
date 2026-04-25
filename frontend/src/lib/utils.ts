import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPrice(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPct(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

/**
 * 将 [0,1] 区间的比例（ratio）格式化为百分比字符串。
 *
 * 典型用途：后端返回的 `cvd_converge_ratio`（0.7283）/
 * `imbalance_green_ratio`（1.0）/ `purity_ratio` 等字段都是 0-1 小数。
 *
 * 与 `formatPct` 的区别：`formatPct` 期望输入已经是百分比口径（12.09 → "12.09%"），
 * 而 `formatRatio` 期望输入是 0-1 小数（0.7283 → "72.83%"）。
 */
export function formatRatio(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/** ms 时间戳 → 本地 HH:mm:ss */
export function formatTs(ms: number): string {
  return new Date(ms).toLocaleTimeString("zh-CN", { hour12: false });
}

/** ISO 字符串 → 本地 HH:mm:ss.SSS */
export function formatIsoTs(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour12: false }) + "." +
    String(d.getMilliseconds()).padStart(3, "0");
}

/** ms 时间戳 → 本地 YYYY-MM-DD HH:mm */
export function formatDateTime(ms: number): string {
  const d = new Date(ms);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

/** uptime 秒 → 人类可读 */
export function formatUptime(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m ${sec % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

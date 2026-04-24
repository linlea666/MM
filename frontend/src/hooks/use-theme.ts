import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { fetchConfigSnapshot } from "@/lib/api";

/**
 * V1.1 · 大屏主题注入 hook
 *
 * 从 /api/config 读取 ui.theme / ui.theme_primary_hex / ui.theme_accent_hex /
 * ui.theme_background_hex，把 data-theme 和 CSS 变量写入 document。
 *
 * 设计原则：
 *   - 加载前用默认样式兜底（避免白屏闪烁）；
 *   - 主题字段任一缺失则用 globals.css 中的 :root 默认值；
 *   - 与现有配置热更新链路联动（queryClient invalidate → refetch → 重新写入）。
 */

type UiSection = {
  theme?: string;
  theme_primary_hex?: string;
  theme_accent_hex?: string;
  theme_background_hex?: string;
};

const HEX_RE = /^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/;

function safeHex(v: unknown, fallback: string): string {
  if (typeof v === "string" && HEX_RE.test(v)) return v;
  return fallback;
}

export function useTheme(): void {
  const q = useQuery({
    queryKey: ["config-snapshot", "theme"],
    queryFn: fetchConfigSnapshot,
    staleTime: 60_000,
    select: (data) => {
      const ui = (data.values as { ui?: UiSection }).ui ?? {};
      return {
        theme: typeof ui.theme === "string" ? ui.theme : "command_center",
        primary: safeHex(ui.theme_primary_hex, "#16D9E3"),
        accent: safeHex(ui.theme_accent_hex, "#58A6FF"),
        background: safeHex(ui.theme_background_hex, "#0A1628"),
      };
    },
  });

  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    // 默认值：command_center + 深海蓝赛博青，避免首次 fetch 前裸露默认主题
    const theme = q.data?.theme ?? "command_center";
    const primary = q.data?.primary ?? "#16D9E3";
    const accent = q.data?.accent ?? "#58A6FF";
    const background = q.data?.background ?? "#0A1628";

    root.setAttribute("data-theme", theme);
    body.setAttribute("data-theme", theme);
    root.style.setProperty("--theme-primary", primary);
    root.style.setProperty("--theme-accent", accent);
    root.style.setProperty("--theme-background", background);
  }, [q.data?.theme, q.data?.primary, q.data?.accent, q.data?.background]);
}

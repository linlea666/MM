import { Link, NavLink } from "react-router-dom";
import { Activity, List, Settings, Terminal, Radar } from "lucide-react";
import { cn } from "@/lib/utils";
import { SymbolSwitcher } from "./symbol-switcher";
import { SystemHealthBadge } from "./system-health-badge";

const TABS = [
  { to: "/", label: "作战大屏", icon: Radar, end: true },
  { to: "/subscriptions", label: "订阅管理", icon: List },
  { to: "/config", label: "规则配置", icon: Settings },
  { to: "/logs", label: "日志面板", icon: Terminal },
];

export function TopBar() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1680px] items-center gap-4 px-4">
        <Link to="/" className="flex items-center gap-2 font-semibold">
          <Activity className="h-5 w-5 text-primary" />
          <span className="tracking-wide">MM · 交易作战指挥</span>
        </Link>

        <nav className="ml-4 flex items-center gap-1">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                )
              }
            >
              <t.icon className="h-4 w-4" />
              {t.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <SymbolSwitcher />
          <SystemHealthBadge />
        </div>
      </div>
    </header>
  );
}

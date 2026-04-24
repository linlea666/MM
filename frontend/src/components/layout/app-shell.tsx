import { Outlet } from "react-router-dom";
import { TopBar } from "./top-bar";
import { useTheme } from "@/hooks/use-theme";

export function AppShell() {
  useTheme();
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <main className="mx-auto w-full max-w-[1680px] flex-1 px-4 py-4">
        <Outlet />
      </main>
    </div>
  );
}

import { Outlet } from "react-router-dom";
import { TopBar } from "./top-bar";

export function AppShell() {
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <main className="mx-auto w-full max-w-[1680px] flex-1 px-4 py-4">
        <Outlet />
      </main>
    </div>
  );
}

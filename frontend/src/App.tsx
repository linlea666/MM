import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/app-shell";
import DashboardPage from "@/pages/dashboard-page";
import ConfigPage from "@/pages/config-page";
import LogsPage from "@/pages/logs-page";
import SubscriptionsPage from "@/pages/subscriptions-page";
import IndicatorsPage from "@/pages/indicators-page";
import AnalysisPage from "@/pages/analysis-page";
import AnalysisReportPage from "@/pages/analysis-report-page";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="/indicators" element={<IndicatorsPage />} />
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="/analysis/:reportId" element={<AnalysisReportPage />} />
            <Route path="/subscriptions" element={<SubscriptionsPage />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

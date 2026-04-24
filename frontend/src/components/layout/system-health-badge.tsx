import { useQuery } from "@tanstack/react-query";
import { fetchSystemHealth } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { formatUptime } from "@/lib/utils";
import { CircleCheck, CircleX, Loader2 } from "lucide-react";

export function SystemHealthBadge() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["system-health"],
    queryFn: fetchSystemHealth,
    refetchInterval: 10_000,
  });

  if (isLoading) {
    return (
      <Badge variant="outline" className="gap-1 font-normal">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span className="text-xs">检查中</span>
      </Badge>
    );
  }

  if (isError || !data) {
    return (
      <Badge variant="destructive" className="gap-1 font-normal">
        <CircleX className="h-3 w-3" />
        <span className="text-xs">后端离线</span>
      </Badge>
    );
  }

  const variant = data.scheduler_running ? "success" : "warning";
  const running = data.scheduler_running ? "采集运行中" : "采集未启动";
  return (
    <Badge variant={variant} className="gap-1 font-normal">
      <CircleCheck className="h-3 w-3" />
      <span className="text-xs">
        {running} · v{data.app_version} · {formatUptime(data.uptime_seconds)}
      </span>
    </Badge>
  );
}

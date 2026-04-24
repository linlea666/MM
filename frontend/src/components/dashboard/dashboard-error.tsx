import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, RefreshCw, Inbox } from "lucide-react";

interface Props {
  error: Error;
  onRetry?: () => void;
  symbol: string;
  tf: string;
}

export function DashboardError({ error, onRetry, symbol, tf }: Props) {
  const status = (error as unknown as { response?: { status?: number } })
    ?.response?.status;
  const noData = status === 404;

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        {noData ? (
          <>
            <Inbox className="h-10 w-10 text-muted-foreground" />
            <div className="text-base font-medium">
              {symbol} / {tf} 暂无可用快照
            </div>
            <div className="max-w-md text-sm text-muted-foreground">
              可能原因：该币种/周期尚未完成首轮采集，或所需原子数据缺失。<br />
              请稍候 30~60 秒再刷新，或在订阅管理中确认已激活该币种。
            </div>
          </>
        ) : (
          <>
            <AlertCircle className="h-10 w-10 text-destructive" />
            <div className="text-base font-medium">快照加载失败</div>
            <div className="max-w-md text-sm text-muted-foreground">
              {(error as { friendly?: string }).friendly ?? error.message}
            </div>
          </>
        )}
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-2">
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            重试
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

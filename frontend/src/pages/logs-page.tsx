import { useState } from "react";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

import { LogSummaryCard } from "@/components/logs/log-summary-card";
import {
  EMPTY_FILTER,
  LogFilterBar,
  type LogFilter,
} from "@/components/logs/log-filter-bar";
import { LogQueryTable } from "@/components/logs/log-query-table";
import { LogLiveTail } from "@/components/logs/log-live-tail";

export default function LogsPage() {
  const [filter, setFilter] = useState<LogFilter>(EMPTY_FILTER);

  return (
    <div className="grid gap-4">
      <LogSummaryCard />

      <LogFilterBar filter={filter} onChange={setFilter} />

      <Tabs defaultValue="query">
        <TabsList>
          <TabsTrigger value="query">查询历史</TabsTrigger>
          <TabsTrigger value="tail">实时尾部</TabsTrigger>
        </TabsList>

        <TabsContent value="query">
          <LogQueryTable filter={filter} />
        </TabsContent>
        <TabsContent value="tail">
          <LogLiveTail filter={filter} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

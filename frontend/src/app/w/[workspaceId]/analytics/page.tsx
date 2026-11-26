"use client";

import { useQuery } from "@tanstack/react-query";
import { use, useState } from "react";
import { SingleBarChart, SingleLineChart, StatTile } from "@/components/charts";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Analytics } from "@/lib/types";

const usd = (v: number) => `$${v < 1 ? v.toFixed(3) : v.toFixed(2)}`;

export default function AnalyticsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const [days, setDays] = useState(14);
  const [showTable, setShowTable] = useState(false);
  const q = useQuery({
    queryKey: ["analytics", workspaceId, days],
    queryFn: () => api<Analytics>(`/api/workspaces/${workspaceId}/analytics?days=${days}`),
  });
  const a = q.data;
  const daily = (a?.daily ?? []) as unknown as Record<string, number | string>[];

  return (
    <div>
      <PageHeader
        title="Analytics"
        description="Usage, latency, token spend and answer quality for this workspace."
        actions={
          <Select aria-label="Time range" value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-36">
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </Select>
        }
      />
      <div className="flex flex-col gap-4 p-6">
        {q.error ? (
          <ErrorState message={q.error.message} onRetry={() => q.refetch()} />
        ) : !a ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile label="Queries" value={a.total_queries.toLocaleString()} hint={`${a.documents} docs · ${a.chunks} chunks`} />
              <StatTile label="Avg latency" value={`${Math.round(a.avg_latency_ms)} ms`} hint={`p95 ${Math.round(a.p95_latency_ms)} ms`} />
              <StatTile label="Estimated cost" value={usd(a.total_cost_usd)} hint={`${a.total_tokens.toLocaleString()} tokens`} />
              <StatTile
                label="Grounded answers"
                value={`${(a.grounded_rate * 100).toFixed(1)}%`}
                hint={`${a.feedback_up} helpful · ${a.feedback_down} unhelpful`}
              />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Queries per day</CardTitle>
                </CardHeader>
                <CardContent>
                  <SingleBarChart data={daily} x="day" y="queries" label="Queries" />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Average latency (ms)</CardTitle>
                </CardHeader>
                <CardContent>
                  <SingleLineChart data={daily} x="day" y="avg_latency_ms" label="Avg latency" format={(v) => `${Math.round(v)}`} />
                </CardContent>
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader>
                  <CardTitle>Estimated cost per day (USD)</CardTitle>
                </CardHeader>
                <CardContent>
                  <SingleBarChart data={daily} x="day" y="cost_usd" label="Cost" format={usd} />
                </CardContent>
              </Card>
            </div>
            <div>
              <button type="button" className="text-sm text-primary underline" onClick={() => setShowTable(!showTable)}>
                {showTable ? "Hide" : "Show"} data table
              </button>
              {showTable && (
                <div className="mt-2 overflow-x-auto rounded-lg border border-border bg-card">
                  <table className="w-full text-sm tabular-nums">
                    <thead className="text-left text-muted-foreground">
                      <tr>
                        {["Day", "Queries", "Avg latency (ms)", "Prompt tokens", "Completion tokens", "Cost"].map((h) => (
                          <th key={h} className="p-2 font-medium">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {a.daily.map((d) => (
                        <tr key={d.day} className="border-t border-border">
                          <td className="p-2">{d.day}</td>
                          <td className="p-2">{d.queries}</td>
                          <td className="p-2">{Math.round(d.avg_latency_ms)}</td>
                          <td className="p-2">{d.prompt_tokens}</td>
                          <td className="p-2">{d.completion_tokens}</td>
                          <td className="p-2">{usd(d.cost_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

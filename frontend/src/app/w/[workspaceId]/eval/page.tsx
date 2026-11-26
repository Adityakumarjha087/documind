"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { use, useState } from "react";
import { toast } from "sonner";
import { GroupedBarChart } from "@/components/charts";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, EmptyState, ErrorState, Skeleton, Spinner } from "@/components/ui/feedback";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { api, json } from "@/lib/api";
import { parseEvalInput } from "@/lib/eval-input";
import { canAdmin, useWorkspace } from "@/lib/hooks";
import type { EvalRun } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const METRICS = [
  { key: "faithfulness", label: "Faithfulness" },
  { key: "answer_relevancy", label: "Answer relevancy" },
  { key: "context_precision", label: "Context precision" },
  { key: "context_recall", label: "Context recall" },
];

const DEFAULT_SET = `How many days of paid time off do employees get per year? | Employees accrue 21 days of paid time off per year.
When must security incidents be reported? | Within one hour of discovery.
How much does the Growth plan cost? | 59 USD per user per month.`;

const fmt = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

export default function EvalPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const base = `/api/workspaces/${workspaceId}/evals`;
  const qc = useQueryClient();
  const { data: ws } = useWorkspace(workspaceId);
  const [name, setName] = useState("Evaluation run");
  const [judge, setJudge] = useState("heuristic");
  const [text, setText] = useState(DEFAULT_SET);
  const [selected, setSelected] = useState<string | null>(null);

  const runs = useQuery({
    queryKey: ["evals", workspaceId],
    queryFn: () => api<EvalRun[]>(base),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "running") ? 1500 : false),
  });

  const create = useMutation({
    mutationFn: () =>
      api<EvalRun>(base, { method: "POST", ...json({ name, judge, questions: parseEvalInput(text) }) }),
    onSuccess: (run) => {
      setSelected(run.id);
      toast.success("Evaluation started");
      qc.invalidateQueries({ queryKey: ["evals", workspaceId] });
    },
    onError: (e) => toast.error(e.message),
  });

  const list = runs.data ?? [];
  const active = list.find((r) => r.id === selected) ?? list[0];
  const chartData = list
    .filter((r) => r.status === "completed")
    .slice(0, 6)
    .reverse()
    .map((r) => ({ run: r.name.slice(0, 18), ...r.summary }));

  return (
    <div>
      <PageHeader
        title="Evaluation"
        description="RAGAS-style metrics (faithfulness, answer relevancy, context precision/recall) on a question set."
      />
      <div className="grid gap-4 p-6 xl:grid-cols-3">
        {canAdmin(ws) && (
          <Card>
            <CardHeader>
              <CardTitle>New run</CardTitle>
              <CardDescription>One question per line. Add a reference answer after “|”.</CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!parseEvalInput(text).length) return toast.error("Add at least one question");
                  create.mutate();
                }}
              >
                <div className="flex flex-col gap-1">
                  <Label htmlFor="eval-name">Name</Label>
                  <Input id="eval-name" value={name} onChange={(e) => setName(e.target.value)} required />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="eval-judge">Judge</Label>
                  <Select id="eval-judge" value={judge} onChange={(e) => setJudge(e.target.value)}>
                    <option value="heuristic">Heuristic (offline, deterministic)</option>
                    <option value="llm">LLM-as-judge (uses configured provider)</option>
                  </Select>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="eval-questions">Questions</Label>
                  <Textarea id="eval-questions" rows={8} value={text} onChange={(e) => setText(e.target.value)} />
                </div>
                <Button type="submit" disabled={create.isPending}>
                  <FlaskConical className="h-4 w-4" aria-hidden /> Run evaluation
                </Button>
              </form>
            </CardContent>
          </Card>
        )}
        <Card className={canAdmin(ws) ? "xl:col-span-2" : "xl:col-span-3"}>
          <CardHeader>
            <CardTitle>Metrics by run</CardTitle>
            <CardDescription>Last {chartData.length} completed runs · higher is better</CardDescription>
          </CardHeader>
          <CardContent>
            {runs.isLoading ? (
              <Skeleton className="h-64" />
            ) : runs.error ? (
              <ErrorState message={runs.error.message} onRetry={() => runs.refetch()} />
            ) : chartData.length ? (
              <GroupedBarChart data={chartData} x="run" keys={METRICS} />
            ) : (
              <EmptyState title="No completed runs yet" description="Start a run to see metrics here." />
            )}
          </CardContent>
        </Card>
      </div>

      {list.length > 0 && (
        <div className="grid gap-4 px-6 pb-8 xl:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Runs</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-1">
                {list.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(r.id)}
                      aria-pressed={active?.id === r.id}
                      className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted aria-pressed:bg-accent"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{r.name}</span>
                        <span className="text-xs text-muted-foreground">{formatDate(r.created_at)}</span>
                      </span>
                      <Badge tone={r.status === "completed" ? "success" : r.status === "failed" ? "danger" : "info"}>
                        {r.status}
                      </Badge>
                    </button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          {active && (
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>{active.name}</CardTitle>
                <CardDescription>
                  Judge: {active.config.judge ?? "heuristic"}
                  {active.config.error && ` · Error: ${active.config.error}`}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {active.status === "running" ? (
                  <Spinner label="Running questions through the RAG pipeline…" />
                ) : (
                  <>
                    <dl className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                      {METRICS.map((m) => (
                        <div key={m.key} className="rounded-md bg-muted p-3">
                          <dt className="text-xs text-muted-foreground">{m.label}</dt>
                          <dd className="text-lg font-semibold tabular-nums">{fmt(active.summary[m.key])}</dd>
                        </div>
                      ))}
                    </dl>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="text-left text-muted-foreground">
                          <tr>
                            <th className="p-2 font-medium">Question</th>
                            <th className="p-2 font-medium">Faith.</th>
                            <th className="p-2 font-medium">Relev.</th>
                            <th className="p-2 font-medium">Ctx P.</th>
                            <th className="p-2 font-medium">Ctx R.</th>
                            <th className="p-2 font-medium">Grounded</th>
                          </tr>
                        </thead>
                        <tbody>
                          {active.results.map((r, i) => (
                            <tr key={i} className="border-t border-border align-top">
                              <td className="p-2">
                                <p className="font-medium">{r.question}</p>
                                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{r.answer}</p>
                              </td>
                              <td className="p-2 tabular-nums">{fmt(r.faithfulness)}</td>
                              <td className="p-2 tabular-nums">{fmt(r.answer_relevancy)}</td>
                              <td className="p-2 tabular-nums">{fmt(r.context_precision)}</td>
                              <td className="p-2 tabular-nums">{fmt(r.context_recall)}</td>
                              <td className="p-2">
                                {r.grounded ? <Badge tone="success">Yes</Badge> : <Badge tone="warning">Refused</Badge>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

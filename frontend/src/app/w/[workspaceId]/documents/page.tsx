"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, RefreshCw, Trash2, Upload } from "lucide-react";
import { use, useRef, useState } from "react";
import { toast } from "sonner";
import { DocumentStatus, isProcessing } from "@/components/document-status";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Input, Label, Select } from "@/components/ui/input";
import { api, json } from "@/lib/api";
import type { DocumentItem } from "@/lib/types";
import { cn, formatBytes, formatDate } from "@/lib/utils";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown";

export default function DocumentsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const base = `/api/workspaces/${workspaceId}/documents`;
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [strategy, setStrategy] = useState("recursive");
  const [url, setUrl] = useState("");
  const [dragging, setDragging] = useState(false);
  const [filter, setFilter] = useState("");

  const docs = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => api<DocumentItem[]>(base),
    // Live ingestion progress: poll while anything is still processing.
    refetchInterval: (q) => (q.state.data?.some(isProcessing) ? 1000 : false),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["documents", workspaceId] });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        const form = new FormData();
        form.append("file", file);
        form.append("chunk_strategy", strategy);
        await api(base, { method: "POST", body: form });
      }
    },
    onSuccess: (_, files) => {
      toast.success(`${files.length} file(s) queued for ingestion`);
      refresh();
    },
    onError: (e) => toast.error(e.message),
  });

  const ingestUrl = useMutation({
    mutationFn: () => api(`${base}/url`, { method: "POST", ...json({ url, chunk_strategy: strategy }) }),
    onSuccess: () => {
      setUrl("");
      toast.success("URL queued for ingestion");
      refresh();
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`${base}/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Document deleted");
      refresh();
    },
    onError: (e) => toast.error(e.message),
  });

  const reindex = useMutation({
    mutationFn: (id: string) => api(`${base}/${id}/reindex`, { method: "POST" }),
    onSuccess: refresh,
    onError: (e) => toast.error(e.message),
  });

  const onFiles = (list: FileList | null) => {
    if (list?.length) upload.mutate(Array.from(list));
  };
  const visible = docs.data?.filter((d) => d.title.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <PageHeader title="Documents" description="Upload files or web pages. Everything is isolated to this workspace." />
      <div className="grid gap-4 p-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Upload files</CardTitle>
            <CardDescription>PDF, DOCX, TXT or Markdown · up to 25 MB each</CardDescription>
          </CardHeader>
          <CardContent>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                onFiles(e.dataTransfer.files);
              }}
              className={cn(
                "flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-border p-8 text-center",
                dragging && "border-primary bg-accent",
              )}
            >
              <Upload className="h-8 w-8 text-muted-foreground" aria-hidden />
              <p className="text-sm text-muted-foreground">Drag & drop files here, or</p>
              <Button onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
                {upload.isPending ? "Uploading…" : "Choose files"}
              </Button>
              <input
                ref={fileRef}
                type="file"
                multiple
                accept={ACCEPT}
                className="sr-only"
                aria-label="Upload documents"
                data-testid="file-input"
                onChange={(e) => {
                  onFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Options & web pages</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor="strategy">Chunking strategy</Label>
              <Select id="strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                <option value="recursive">Recursive (structure-aware)</option>
                <option value="semantic">Semantic (topic shifts)</option>
              </Select>
            </div>
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (url) ingestUrl.mutate();
              }}
            >
              <Label htmlFor="url">Ingest a URL</Label>
              <Input
                id="url"
                type="url"
                placeholder="https://example.com/handbook"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
              <Button type="submit" variant="outline" disabled={!url || ingestUrl.isPending}>
                <Link2 className="h-4 w-4" aria-hidden /> Add URL
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <div className="px-6 pb-8">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="font-semibold">Library</h2>
          <Input
            aria-label="Filter documents"
            placeholder="Filter by title…"
            className="max-w-xs"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        {docs.isLoading ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : docs.error ? (
          <ErrorState message={docs.error.message} onRetry={() => docs.refetch()} />
        ) : !visible?.length ? (
          <EmptyState
            title={filter ? "No matching documents" : "No documents yet"}
            description="Upload a file above to start asking questions about it."
          />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="w-full text-sm">
              <thead className="border-b border-border text-left text-muted-foreground">
                <tr>
                  <th className="p-3 font-medium">Title</th>
                  <th className="p-3 font-medium">Type</th>
                  <th className="p-3 font-medium">Status</th>
                  <th className="p-3 font-medium">Chunks</th>
                  <th className="p-3 font-medium">Added</th>
                  <th className="p-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((d) => (
                  <tr key={d.id} className="border-b border-border last:border-0">
                    <td className="p-3">
                      <p className="font-medium">{d.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {d.source_type === "url" ? d.source_uri : formatBytes(d.size_bytes)}
                        {d.num_pages ? ` · ${d.num_pages} pages` : ""} · {d.chunk_strategy}
                      </p>
                    </td>
                    <td className="p-3 uppercase">{d.source_type}</td>
                    <td className="p-3">
                      <DocumentStatus doc={d} />
                    </td>
                    <td className="p-3">{d.num_chunks}</td>
                    <td className="p-3 text-muted-foreground">{formatDate(d.created_at)}</td>
                    <td className="p-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Re-index ${d.title}`}
                          disabled={isProcessing(d)}
                          onClick={() => reindex.mutate(d.id)}
                        >
                          <RefreshCw className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${d.title}`}
                          onClick={() => window.confirm(`Delete "${d.title}"?`) && remove.mutate(d.id)}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

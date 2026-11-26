"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, X } from "lucide-react";
import { api } from "@/lib/api";
import type { ChunkItem, Citation } from "@/lib/types";
import { Button } from "./ui/button";
import { Badge, ErrorState, Skeleton } from "./ui/feedback";

export function SourcePanel({
  workspaceId,
  citation,
  onClose,
}: {
  workspaceId: string;
  citation: Citation;
  onClose: () => void;
}) {
  const chunk = useQuery({
    queryKey: ["chunk", workspaceId, citation.chunk_id],
    queryFn: () => api<ChunkItem>(`/api/workspaces/${workspaceId}/chunks/${citation.chunk_id}`),
  });
  return (
    <aside aria-label="Source preview" className="flex h-full flex-col border-l border-border bg-card">
      <div className="flex items-start justify-between gap-2 border-b border-border p-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <FileText className="h-3 w-3" aria-hidden /> Source [{citation.index}]
          </p>
          <h2 className="truncate font-semibold">{citation.document_title}</h2>
          <div className="mt-1 flex flex-wrap gap-1">
            {citation.page && <Badge>Page {citation.page}</Badge>}
            {citation.section && <Badge>{citation.section}</Badge>}
            <Badge tone="info">Relevance {(citation.score * 100).toFixed(0)}%</Badge>
          </div>
        </div>
        <Button variant="ghost" size="icon" aria-label="Close source preview" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 text-sm leading-relaxed">
        {chunk.isLoading ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4" />
            <Skeleton className="h-4" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : chunk.error ? (
          <ErrorState message="This source is no longer available." />
        ) : (
          <p className="whitespace-pre-wrap" data-testid="source-text">
            {chunk.data?.content}
          </p>
        )}
      </div>
    </aside>
  );
}

import type { DocumentItem } from "@/lib/types";
import { Badge, Progress } from "./ui/feedback";

const LABEL: Record<DocumentItem["status"], string> = {
  queued: "Queued",
  parsing: "Parsing",
  chunking: "Chunking",
  embedding: "Embedding",
  ready: "Ready",
  failed: "Failed",
};

export function DocumentStatus({ doc }: { doc: DocumentItem }) {
  if (doc.status === "ready") return <Badge tone="success">{LABEL.ready}</Badge>;
  if (doc.status === "failed")
    return (
      <span className="flex flex-col gap-1">
        <Badge tone="danger">{LABEL.failed}</Badge>
        {doc.error && <span className="text-xs text-destructive">{doc.error}</span>}
      </span>
    );
  return (
    <span className="flex min-w-32 flex-col gap-1">
      <span className="text-xs text-muted-foreground">
        {LABEL[doc.status]} · {doc.progress}%
      </span>
      <Progress value={doc.progress} label={`Ingestion progress for ${doc.title}`} />
    </span>
  );
}

export const isProcessing = (d: DocumentItem) => d.status !== "ready" && d.status !== "failed";

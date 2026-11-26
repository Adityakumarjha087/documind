"use client";

import { Bot, ShieldAlert, ThumbsDown, ThumbsUp, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { citationIndex, linkCitations } from "@/lib/citations";
import type { Citation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "./ui/feedback";

export interface ViewMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  grounded: boolean;
  rewritten_query?: string | null;
  feedback?: number | null;
  streaming?: boolean;
}

interface Props {
  message: ViewMessage;
  onCite: (c: Citation) => void;
  onFeedback?: (rating: 1 | -1) => void;
}

export function ChatMessage({ message, onCite, onFeedback }: Props) {
  const isUser = message.role === "user";
  const cited = message.citations.filter((c) => c.cited);
  const shown = cited.length ? cited : message.citations;

  return (
    <article
      aria-label={isUser ? "Your message" : "Assistant answer"}
      className={cn("flex gap-3", isUser && "flex-row-reverse")}
    >
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted",
        )}
        aria-hidden
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={cn("flex max-w-[85%] flex-col gap-2", isUser && "items-end")}>
        <div
          className={cn(
            "rounded-lg px-4 py-2 text-sm",
            isUser ? "bg-primary text-primary-foreground" : "border border-border bg-card",
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose-answer" data-testid="answer">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => {
                    const idx = citationIndex(href);
                    const c = idx ? message.citations[idx - 1] : undefined;
                    if (c) {
                      return (
                        <button
                          type="button"
                          onClick={() => onCite(c)}
                          className="mx-0.5 rounded bg-primary/15 px-1 text-xs font-semibold text-primary hover:bg-primary/25"
                          aria-label={`Source ${idx}: ${c.document_title}${c.page ? `, page ${c.page}` : ""}`}
                        >
                          {idx}
                        </button>
                      );
                    }
                    return (
                      <a href={href} target="_blank" rel="noreferrer" className="text-primary underline">
                        {children}
                      </a>
                    );
                  },
                }}
              >
                {linkCitations(message.content, message.citations.length)}
              </ReactMarkdown>
              {message.streaming && <span className="ml-1 inline-block h-4 w-1.5 animate-pulse bg-foreground align-middle" />}
            </div>
          )}
        </div>
        {!isUser && (
          <div className="flex flex-wrap items-center gap-2">
            {!message.grounded && !message.streaming && (
              <Badge tone="warning">
                <ShieldAlert className="mr-1 h-3 w-3" aria-hidden /> Not enough context
              </Badge>
            )}
            {message.rewritten_query && (
              <span className="text-xs text-muted-foreground" title="Follow-up rewritten for retrieval">
                Searched: “{message.rewritten_query}”
              </span>
            )}
            {shown.map((c) => (
              <button
                key={c.chunk_id}
                type="button"
                onClick={() => onCite(c)}
                className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-muted"
              >
                [{c.index}] {c.document_title}
                {c.page ? ` · p.${c.page}` : ""}
              </button>
            ))}
            {onFeedback && !message.streaming && (
              <span className="ml-auto flex gap-1">
                <button
                  type="button"
                  aria-label="Helpful answer"
                  aria-pressed={message.feedback === 1}
                  onClick={() => onFeedback(1)}
                  className={cn("rounded p-1 hover:bg-muted", message.feedback === 1 && "text-success")}
                >
                  <ThumbsUp className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label="Unhelpful answer"
                  aria-pressed={message.feedback === -1}
                  onClick={() => onFeedback(-1)}
                  className={cn("rounded p-1 hover:bg-muted", message.feedback === -1 && "text-destructive")}
                >
                  <ThumbsDown className="h-4 w-4" />
                </button>
              </span>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

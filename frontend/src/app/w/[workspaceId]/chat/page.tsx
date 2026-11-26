"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Send, Square, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, use, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ChatMessage, type ViewMessage } from "@/components/chat-message";
import { SourcePanel } from "@/components/source-panel";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/feedback";
import { Textarea } from "@/components/ui/input";
import { api, json } from "@/lib/api";
import type { Citation, Conversation, ConversationDetail } from "@/lib/types";
import { useChatStream } from "@/lib/use-chat-stream";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "Summarise the key points of our documents",
  "What is the remote work policy?",
  "How do I report a security incident?",
];

function Chat({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const search = useSearchParams();
  const urlConversationId = search.get("c");
  // A brand-new conversation is shown under its id before the URL catches up (set after the
  // first answer streams), so the chat never blanks out in between.
  const [pendingId, setPendingId] = useState<string | null>(null);
  const conversationId = urlConversationId ?? pendingId;
  const qc = useQueryClient();
  const base = `/api/workspaces/${workspaceId}`;
  const [input, setInput] = useState("");
  const [source, setSource] = useState<Citation | null>(null);
  const { answer, send, reset, stop } = useChatStream(workspaceId);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (urlConversationId) setPendingId(null);
  }, [urlConversationId]);
  // How many saved messages existed when the current question was sent; once the saved
  // conversation holds the new question + answer, the live copy is hidden (no duplicates).
  const savedAtSend = useRef(0);

  const conversations = useQuery({
    queryKey: ["conversations", workspaceId],
    queryFn: () => api<Conversation[]>(`${base}/conversations`),
  });
  const detail = useQuery({
    queryKey: ["conversation", workspaceId, conversationId],
    queryFn: () => api<ConversationDetail>(`${base}/conversations/${conversationId}`),
    enabled: !!conversationId,
  });

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [answer?.content, detail.data?.messages.length]);

  const feedback = useMutation({
    mutationFn: ({ id, rating }: { id: string; rating: 1 | -1 }) =>
      api(`${base}/messages/${id}/feedback`, { method: "PUT", ...json({ rating }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversation", workspaceId, conversationId] }),
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`${base}/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: ["conversations", workspaceId] });
      if (id === conversationId) {
        setPendingId(null);
        router.push(`/w/${workspaceId}/chat`);
      }
    },
  });

  const streaming = !!answer && !answer.done;

  async function submit(text: string) {
    const question = text.trim();
    if (!question || streaming) return;
    setInput("");
    let cid = conversationId;
    const isNew = !cid;
    savedAtSend.current = isNew ? 0 : (detail.data?.messages.length ?? 0);
    try {
      if (!cid) {
        const conv = await api<Conversation>(`${base}/conversations`, { method: "POST", ...json({}) });
        cid = conv.id;
        setPendingId(cid);
      }
      // Stream first; changing the URL mid-stream can re-render the page and strand the
      // in-flight answer, so a new conversation's URL is only set once the answer is saved.
      const result = await send(cid, question);
      if (result.error) toast.error(result.error);
      // Load the saved conversation before dropping the live copy, so nothing flickers.
      await qc.fetchQuery({
        queryKey: ["conversation", workspaceId, cid],
        queryFn: () => api<ConversationDetail>(`${base}/conversations/${cid}`),
        staleTime: 0,
      });
      await qc.invalidateQueries({ queryKey: ["conversations", workspaceId] });
      if (isNew) router.replace(`/w/${workspaceId}/chat?c=${cid}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      reset();
    }
  }

  const persisted: ViewMessage[] = conversationId ? (detail.data?.messages ?? []) : [];
  const liveSaved = !!answer?.done && persisted.length >= savedAtSend.current + 2;
  const live: ViewMessage[] = answer && !liveSaved
    ? [
        { id: "pending-q", role: "user", content: answer.question, citations: [], grounded: true },
        {
          id: "pending-a",
          role: "assistant",
          content: answer.content || (answer.done ? "" : "Searching your documents…"),
          citations: answer.citations,
          grounded: answer.grounded,
          rewritten_query: answer.rewritten_query,
          streaming: !answer.done,
        },
      ]
    : [];
  const messages = [...persisted, ...live];

  return (
    <div className="flex h-full">
      <section aria-label="Conversations" className="hidden w-64 shrink-0 flex-col border-r border-border lg:flex">
        <div className="p-3">
          <Button className="w-full" onClick={() => {
              setPendingId(null);
              router.push(`/w/${workspaceId}/chat`);
            }}>
            <MessageSquarePlus className="h-4 w-4" aria-hidden /> New chat
          </Button>
        </div>
        <ul className="flex-1 overflow-y-auto px-2 pb-2">
          {conversations.isLoading &&
            [0, 1, 2].map((i) => <Skeleton key={i} className="mx-1 my-1 h-8" />)}
          {conversations.data?.length === 0 && (
            <li className="px-2 text-sm text-muted-foreground">No conversations yet.</li>
          )}
          {conversations.data?.map((c) => (
            <li key={c.id} className="group flex items-center">
              <Link
                href={`/w/${workspaceId}/chat?c=${c.id}`}
                aria-current={c.id === conversationId ? "page" : undefined}
                className={cn(
                  "flex-1 truncate rounded-md px-3 py-2 text-sm hover:bg-muted",
                  c.id === conversationId && "bg-accent text-primary",
                )}
              >
                {c.title}
              </Link>
              <button
                type="button"
                aria-label={`Delete conversation ${c.title}`}
                onClick={() => remove.mutate(c.id)}
                className="rounded p-1 opacity-0 hover:bg-muted focus:opacity-100 group-hover:opacity-100"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Chat" className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 overflow-y-auto px-4 py-6" aria-live="polite">
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {conversationId && detail.isLoading && <Skeleton className="h-24" />}
            {detail.error && <ErrorState message={detail.error.message} onRetry={() => detail.refetch()} />}
            {messages.length === 0 && !detail.isLoading && (
              <EmptyState
                title="Ask anything about your documents"
                description="Answers are grounded in this workspace's documents and cite their sources."
                action={
                  <div className="mt-2 flex flex-wrap justify-center gap-2">
                    {SUGGESTIONS.map((s) => (
                      <Button key={s} variant="outline" size="sm" onClick={() => submit(s)}>
                        {s}
                      </Button>
                    ))}
                  </div>
                }
              />
            )}
            {messages.map((m) => (
              <ChatMessage
                key={m.id}
                message={m}
                onCite={setSource}
                onFeedback={
                  m.role === "assistant" && !m.id.startsWith("pending")
                    ? (rating) => feedback.mutate({ id: m.id, rating })
                    : undefined
                }
              />
            ))}
            <div ref={bottom} />
          </div>
        </div>
        <form
          className="border-t border-border p-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit(input);
          }}
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <Textarea
              aria-label="Ask a question"
              placeholder="Ask a question about your documents…"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(input);
                }
              }}
              className="resize-none"
            />
            {streaming ? (
              <Button type="button" variant="outline" size="icon" aria-label="Stop generating" onClick={stop}>
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button type="submit" size="icon" aria-label="Send" disabled={!input.trim()}>
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
        </form>
      </section>

      {source && (
        <div className="fixed inset-y-0 right-0 z-30 w-full max-w-md md:static md:w-96">
          <SourcePanel workspaceId={workspaceId} citation={source} onClose={() => setSource(null)} />
        </div>
      )}
    </div>
  );
}

export default function ChatPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  return (
    <Suspense>
      <Chat workspaceId={workspaceId} />
    </Suspense>
  );
}

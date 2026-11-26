"use client";

import { useCallback, useRef, useState } from "react";
import { apiFetch } from "./api";
import { readSse } from "./sse";
import type { Citation } from "./types";

export interface StreamingAnswer {
  question: string;
  content: string;
  citations: Citation[];
  rewritten_query: string | null;
  grounded: boolean;
  done: boolean;
  error: string | null;
}

export function useChatStream(workspaceId: string) {
  const [answer, setAnswer] = useState<StreamingAnswer | null>(null);
  const abort = useRef<AbortController | null>(null);

  const send = useCallback(
    async (conversationId: string, question: string): Promise<StreamingAnswer> => {
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      let state: StreamingAnswer = {
        question,
        content: "",
        citations: [],
        rewritten_query: null,
        grounded: true,
        done: false,
        error: null,
      };
      const update = (patch: Partial<StreamingAnswer>) => {
        state = { ...state, ...patch };
        setAnswer(state);
      };
      update({});
      try {
        const res = await apiFetch(`/api/workspaces/${workspaceId}/conversations/${conversationId}/messages`, {
          method: "POST",
          body: JSON.stringify({ content: question }),
          signal: ctrl.signal,
        });
        for await (const ev of readSse(res)) {
          const d = ev.data as Record<string, unknown>;
          if (ev.event === "rewrite") update({ rewritten_query: String(d.query) });
          else if (ev.event === "sources") update({ citations: d.sources as Citation[] });
          else if (ev.event === "token") update({ content: state.content + String(d.text) });
          else if (ev.event === "done")
            update({ citations: d.citations as Citation[], grounded: Boolean(d.grounded), done: true });
          else if (ev.event === "error") update({ error: String(d.message), done: true });
        }
        if (!state.done) update({ done: true });
      } catch (e) {
        if ((e as Error).name !== "AbortError") update({ error: (e as Error).message, done: true });
      }
      return state;
    },
    [workspaceId],
  );

  const reset = useCallback(() => setAnswer(null), []);
  const stop = useCallback(() => abort.current?.abort(), []);
  return { answer, send, reset, stop };
}

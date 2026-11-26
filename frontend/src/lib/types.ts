export type Role = "owner" | "admin" | "member";
export type DocumentStatus = "queued" | "parsing" | "chunking" | "embedding" | "ready" | "failed";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  role: Role;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
}

export interface DocumentItem {
  id: string;
  title: string;
  source_type: string;
  source_uri: string;
  size_bytes: number;
  status: DocumentStatus;
  progress: number;
  error: string | null;
  chunk_strategy: string;
  num_pages: number | null;
  num_chunks: number;
  created_at: string;
}

export interface ChunkItem {
  id: string;
  document_id: string;
  ordinal: number;
  content: string;
  page: number | null;
  section: string | null;
}

export interface Citation {
  index: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  page: number | null;
  section: string | null;
  snippet: string;
  score: number;
  cited: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
}

export interface ChatMessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  rewritten_query: string | null;
  citations: Citation[];
  grounded: boolean;
  created_at: string;
  feedback: number | null;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessageItem[];
}

export interface EvalResult {
  question: string;
  ground_truth: string | null;
  answer: string;
  grounded: boolean;
  num_contexts: number;
  latency_ms: number;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
}

export interface EvalRun {
  id: string;
  name: string;
  status: "running" | "completed" | "failed";
  summary: Record<string, number>;
  results: EvalResult[];
  config: { judge?: string; error?: string };
  created_at: string;
  finished_at: string | null;
}

export interface DailyPoint {
  day: string;
  queries: number;
  avg_latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}

export interface Analytics {
  days: number;
  total_queries: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  total_tokens: number;
  total_cost_usd: number;
  grounded_rate: number;
  feedback_up: number;
  feedback_down: number;
  documents: number;
  chunks: number;
  daily: DailyPoint[];
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown };
}

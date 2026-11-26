import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatMessage, type ViewMessage } from "@/components/chat-message";
import { DocumentStatus } from "@/components/document-status";
import { StatTile } from "@/components/charts";
import { EmptyState, ErrorState } from "@/components/ui/feedback";
import type { Citation, DocumentItem } from "@/lib/types";

const citation: Citation = {
  index: 1,
  chunk_id: "c1",
  document_id: "d1",
  document_title: "Security Policy",
  page: 3,
  section: "Network",
  snippet: "Use the VPN",
  score: 0.82,
  cited: true,
};

describe("ChatMessage", () => {
  it("renders inline citation buttons and source chips that open the source", async () => {
    const onCite = vi.fn();
    const msg: ViewMessage = {
      id: "m1",
      role: "assistant",
      content: "Always use the **VPN** [1].",
      citations: [citation],
      grounded: true,
    };
    render(<ChatMessage message={msg} onCite={onCite} onFeedback={() => {}} />);
    expect(screen.getByText("VPN").tagName).toBe("STRONG");
    await userEvent.click(screen.getByRole("button", { name: "Source 1: Security Policy, page 3" }));
    await userEvent.click(screen.getByRole("button", { name: /\[1\] Security Policy · p.3/ }));
    expect(onCite).toHaveBeenCalledTimes(2);
    expect(onCite).toHaveBeenCalledWith(citation);
  });

  it("shows the guardrail badge and feedback state", async () => {
    const onFeedback = vi.fn();
    render(
      <ChatMessage
        message={{ id: "m2", role: "assistant", content: "I don't know.", citations: [], grounded: false, feedback: 1 }}
        onCite={() => {}}
        onFeedback={onFeedback}
      />,
    );
    expect(screen.getByText("Not enough context")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Helpful answer" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Unhelpful answer" }));
    expect(onFeedback).toHaveBeenCalledWith(-1);
  });

  it("renders user messages as plain text", () => {
    render(
      <ChatMessage message={{ id: "u", role: "user", content: "**hi**", citations: [], grounded: true }} onCite={() => {}} />,
    );
    expect(screen.getByText("**hi**")).toBeInTheDocument();
  });
});

describe("DocumentStatus", () => {
  const doc = (patch: Partial<DocumentItem>): DocumentItem => ({
    id: "1",
    title: "Doc",
    source_type: "pdf",
    source_uri: "k",
    size_bytes: 10,
    status: "ready",
    progress: 100,
    error: null,
    chunk_strategy: "recursive",
    num_pages: 1,
    num_chunks: 2,
    created_at: new Date().toISOString(),
    ...patch,
  });

  it("shows progress while processing", () => {
    render(<DocumentStatus doc={doc({ status: "embedding", progress: 60 })} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "60");
    expect(screen.getByText(/Embedding · 60%/)).toBeInTheDocument();
  });

  it("shows errors for failed documents", () => {
    render(<DocumentStatus doc={doc({ status: "failed", error: "Document is empty" })} />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Document is empty")).toBeInTheDocument();
  });
});

describe("states", () => {
  it("renders empty/error states and stat tiles", async () => {
    const retry = vi.fn();
    render(
      <>
        <EmptyState title="Nothing here" description="Upload something" />
        <ErrorState message="Boom" onRetry={retry} />
        <StatTile label="Queries" value="42" hint="7 days" />
      </>,
    );
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Boom");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    expect(screen.getByText("42")).toBeInTheDocument();
  });
});

describe("ChatMessage security", () => {
  it("never renders raw HTML or javascript: links from model/document text", () => {
    const { container } = render(
      <ChatMessage
        message={{
          id: "x",
          role: "assistant",
          content: 'Hi <script>alert(1)</script><img src=x onerror="alert(2)"> [click](javascript:alert(3))',
          citations: [],
          grounded: true,
        }}
        onCite={() => {}}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const link = container.querySelector("a");
    expect(link?.getAttribute("href") ?? "").not.toMatch(/^javascript:/i);
  });

  it("ignores out-of-range citation markers", () => {
    render(
      <ChatMessage
        message={{ id: "y", role: "assistant", content: "See [7].", citations: [citation], grounded: true }}
        onCite={() => {}}
      />,
    );
    expect(screen.getByText(/See \[7\]/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Source 7/ })).toBeNull();
  });
});

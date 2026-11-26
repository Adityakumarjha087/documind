import { citationIndex, linkCitations } from "@/lib/citations";
import { parseEvalInput } from "@/lib/eval-input";
import { SseParser } from "@/lib/sse";
import { formatBytes } from "@/lib/utils";

describe("SseParser", () => {
  it("parses events split across chunks", () => {
    const p = new SseParser();
    expect(p.push('event: token\ndata: {"text":"Hel')).toEqual([]);
    const events = p.push('lo"}\n\nevent: done\r\ndata: {"ok":true}\r\n\r\n');
    expect(events).toEqual([
      { event: "token", data: { text: "Hello" } },
      { event: "done", data: { ok: true } },
    ]);
  });

  it("falls back to raw text for non-JSON data", () => {
    expect(new SseParser().push("data: plain\n\n")).toEqual([{ event: "message", data: "plain" }]);
  });
});

describe("citations", () => {
  it("links only in-range markers", () => {
    expect(linkCitations("A [1] B [3] C [2](x)", 2)).toBe("A [1](#cite-1) B [3] C [2](x)");
    expect(citationIndex("#cite-4")).toBe(4);
    expect(citationIndex("https://x")).toBeNull();
  });
});

describe("parseEvalInput", () => {
  it("splits questions and optional ground truth", () => {
    expect(parseEvalInput("Q1 | A1\n\n  Q2  \n| orphan")).toEqual([
      { question: "Q1", ground_truth: "A1" },
      { question: "Q2", ground_truth: null },
    ]);
  });
});

it("formats bytes", () => {
  expect(formatBytes(512)).toBe("512 B");
  expect(formatBytes(2048)).toBe("2.0 KB");
  expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
});

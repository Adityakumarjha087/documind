export interface EvalQuestionInput {
  question: string;
  ground_truth: string | null;
}

/** One question per line; an optional reference answer follows " | ". */
export function parseEvalInput(text: string): EvalQuestionInput[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [q, ...rest] = line.split("|");
      const gt = rest.join("|").trim();
      return { question: (q ?? "").trim(), ground_truth: gt || null };
    })
    .filter((q) => q.question.length > 0);
}

/** Turn inline [n] markers into markdown links the renderer can intercept. */
export function linkCitations(text: string, max: number): string {
  return text.replace(/\[(\d+)\](?!\()/g, (m, n: string) => {
    const i = Number(n);
    return i >= 1 && i <= max ? `[${n}](#cite-${n})` : m;
  });
}

export function citationIndex(href: string | undefined): number | null {
  const m = href?.match(/^#cite-(\d+)$/);
  return m ? Number(m[1]) : null;
}

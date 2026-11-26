"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

const axis = { stroke: "var(--muted-foreground)", fontSize: 12, tickLine: false, axisLine: false } as const;
const tooltipStyle = {
  contentStyle: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    color: "var(--foreground)",
    fontSize: 12,
  },
  cursor: { fill: "var(--muted)", opacity: 0.5 },
} as const;

type Row = Record<string, string | number | null>;

interface SingleProps {
  data: Row[];
  x: string;
  y: string;
  label: string;
  format?: (v: number) => string;
}

export function SingleBarChart({ data, x, y, label, format = (v) => String(v) }: SingleProps) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey={x} {...axis} tickFormatter={(d: string) => d.slice(5)} minTickGap={16} />
        <YAxis {...axis} width={48} tickFormatter={(v: number) => format(v)} />
        <Tooltip {...tooltipStyle} formatter={(v) => [format(Number(v)), label]} />
        <Bar dataKey={y} name={label} fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SingleLineChart({ data, x, y, label, format = (v) => String(v) }: SingleProps) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey={x} {...axis} tickFormatter={(d: string) => d.slice(5)} minTickGap={16} />
        <YAxis {...axis} width={48} tickFormatter={(v: number) => format(v)} />
        <Tooltip
          {...tooltipStyle}
          cursor={{ stroke: "var(--muted-foreground)" }}
          formatter={(v) => [format(Number(v)), label]}
        />
        <Line type="monotone" dataKey={y} name={label} stroke={SERIES[0]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Grouped bars: one group per category (x), one bar per metric, fixed slot order. */
export function GroupedBarChart({ data, x, keys }: { data: Row[]; x: string; keys: { key: string; label: string }[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="var(--grid)" />
        <XAxis dataKey={x} {...axis} />
        <YAxis {...axis} width={40} domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={(v: number) => v.toFixed(2)} />
        <Tooltip {...tooltipStyle} formatter={(v) => Number(v).toFixed(3)} />
        <Legend
          itemSorter={null}
          wrapperStyle={{ fontSize: 12 }}
          formatter={(value: string) => <span style={{ color: "var(--foreground)" }}>{value}</span>}
        />
        {keys.map((k, i) => (
          <Bar key={k.key} dataKey={k.key} name={k.label} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={22} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

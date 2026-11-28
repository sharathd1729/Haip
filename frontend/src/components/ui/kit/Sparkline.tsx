// A tiny trend line for a KPI tile: the last few days as one smooth curve, a dot on the latest day, no axes and no text
// (owner, 28 Nov 2026). The curve is a monotone cubic, so it never dips below or overshoots the real values. It inherits the
// tile's colour (currentColor); screen readers get the numbers through `label`.
import { cn } from "@/lib/utils";

/** Path for `values` drawn into a w x h box with `pad` px of breathing room. Exported for tests. */
export function sparkPath(values: number[], w = 48, h = 18, pad = 2.5): { d: string; last: [number, number] } | null {
  if (values.length < 2) return null;
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const pts = values.map((v, i): [number, number] => [
    pad + (i * (w - pad * 2)) / (values.length - 1),
    h - pad - ((v - min) / span) * (h - pad * 2),
  ]);
  const n = pts.length, m: number[] = [], t: number[] = [];
  for (let i = 0; i < n - 1; i++) m[i] = (pts[i + 1][1] - pts[i][1]) / (pts[i + 1][0] - pts[i][0]);
  t[0] = m[0]; t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) t[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  for (let i = 0; i < n - 1; i++) {          // Fritsch-Carlson: keep each segment monotone
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], s = a * a + b * b;
    if (s > 9) { const k = 3 / Math.sqrt(s); t[i] = k * a * m[i]; t[i + 1] = k * b * m[i]; }
  }
  const f = (x: number) => x.toFixed(1);
  let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
  for (let i = 0; i < n - 1; i++) {
    const hx = (pts[i + 1][0] - pts[i][0]) / 3;
    d += ` C${f(pts[i][0] + hx)},${f(pts[i][1] + t[i] * hx)} ${f(pts[i + 1][0] - hx)},${f(pts[i + 1][1] - t[i + 1] * hx)} ${f(pts[i + 1][0])},${f(pts[i + 1][1])}`;
  }
  return { d, last: pts[n - 1] };
}

export function Sparkline({ values, label, width = 48, height = 18, className }: {
  values: number[];
  /** What the line shows, e.g. "New leads, last 7 days: 3, 4, 7, 5, 3, 4, 2". */
  label: string;
  width?: number; height?: number; className?: string;
}) {
  const path = sparkPath(values, width, height);
  if (!path) return null;
  return (
    <svg role="img" aria-label={label} width={width} height={height} viewBox={`0 0 ${width} ${height}`}
      className={cn("shrink-0 overflow-visible", className)}>
      <path d={path.d} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={path.last[0].toFixed(1)} cy={path.last[1].toFixed(1)} r={2.25} fill="currentColor" />
    </svg>
  );
}

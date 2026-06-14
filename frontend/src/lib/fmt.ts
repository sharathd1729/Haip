export function fmt_inr(value: number): string {
  return `₹${Number(value).toLocaleString("en-IN")}`;
}

export function fmtTime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

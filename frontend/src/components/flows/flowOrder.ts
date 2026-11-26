// Wait (delay) helpers shared by the flow canvas: minutes <-> "3 days".
export const DELAY_UNITS = [
  { value: "minutes", label: "minutes", minutes: 1 },
  { value: "hours", label: "hours", minutes: 60 },
  { value: "days", label: "days", minutes: 1440 },
] as const;

export function describeDelay(minutes: number): string {
  if (minutes % 1440 === 0) { const d = minutes / 1440; return `Wait ${d} day${d === 1 ? "" : "s"}`; }
  if (minutes % 60 === 0) { const h = minutes / 60; return `Wait ${h} hour${h === 1 ? "" : "s"}`; }
  return `Wait ${minutes} min`;
}

export function splitDelay(minutes: number): { amount: number; unit: (typeof DELAY_UNITS)[number]["value"] } {
  if (minutes % 1440 === 0) return { amount: minutes / 1440, unit: "days" };
  if (minutes % 60 === 0) return { amount: minutes / 60, unit: "hours" };
  return { amount: minutes, unit: "minutes" };
}

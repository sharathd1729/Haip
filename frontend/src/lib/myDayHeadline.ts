// My day's header line. "need action now" is work_queue_service's people_waiting, the SAME number as the nav "Now"
// badge and Home's "Waiting on the team"; "older" = people whose every item has gone cold (severity "stale").
export interface HeadlineCounts { total: number; people: number; people_waiting?: number; unowned?: number }

export function myDayHeadline(q: HeadlineCounts | undefined): string {
  if (!q) return "Loading…";
  if (q.total === 0) return "Nobody is waiting. Nice.";
  const now = q.people_waiting ?? q.people;
  const older = Math.max(0, q.people - now);
  const parts = [`${q.people} waiting`, `${now} need action now`];
  if (older) parts.push(`${older} older`);
  if (q.unowned) parts.push(`${q.unowned} with no owner`);
  return parts.join(" · ");
}

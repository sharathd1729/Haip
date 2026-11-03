// Audit log: resource type -> dashboard URL. Every target must be a real route: there is no team-member page, so a user
// opens the team list with that person highlighted (?member=), never /settings/team/<id> (that was a 404).
const RESOURCE_LINKS: Record<string, (id: string) => string> = {
  guest:   id => `/dashboard/guests/${id}`,
  call:    id => `/dashboard/calls/${id}`,
  inquiry: id => `/dashboard/leads/${id}`,
  user:    id => `/dashboard/settings/team?member=${encodeURIComponent(id)}`,
};

export function resourceLink(type?: string, id?: string): string | null {
  if (!type || !id) return null;
  const link = RESOURCE_LINKS[type];
  return link ? link(id) : null;
}

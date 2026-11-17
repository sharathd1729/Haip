// Each workspace's own address (workspace redesign Phase 1): genhaip.com/w/<slug>/inbox. The pages still live under
// app/dashboard; middleware.ts rewrites /w/<slug>/... to them and sends /dashboard/... links to the signed-in workspace's
// address. Code that compares paths works on the app path (/dashboard/...) via these helpers (hook: useAppPathname.ts;
// this file stays free of React so middleware can import it). Yaad's personal
// workspaces (slug "me-...") keep /dashboard/me: they have no public address.
const WS_PREFIX = /^\/w\/([a-z0-9][a-z0-9-]*)(?=\/|$)/;

export function workspaceSlugOf(pathname: string): string | null {
  return pathname.match(WS_PREFIX)?.[1] ?? null;
}

/** /w/neelgiri/inbox -> /dashboard/inbox; anything else unchanged. */
export function toAppPath(pathname: string): string {
  const m = pathname.match(WS_PREFIX);
  return m ? "/dashboard" + pathname.slice(m[0].length) : pathname;
}

/** /dashboard/inbox -> /w/neelgiri/inbox; anything else unchanged. */
export function toWorkspacePath(pathname: string, slug: string): string {
  if (pathname !== "/dashboard" && !pathname.startsWith("/dashboard/")) return pathname;
  return `/w/${slug}` + pathname.slice("/dashboard".length);
}

export function hasPublicAddress(slug: string | null | undefined): slug is string {
  return !!slug && !slug.startsWith("me-") && /^[a-z0-9][a-z0-9-]*$/.test(slug);
}

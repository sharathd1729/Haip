// Where a sign-in may send someone, shared by the sign-in forms and the middleware.

// A Yaad screen is /dashboard/me or below it. Never a bare prefix test: "/dashboard/messaging" starts with "/dashboard/me",
// and that sent signed-out WhatsApp links to Yaad's sign-in, which then landed the Yaad user on HAIP's WhatsApp page.
export const isYaadScreen = (path: string) => path === "/dashboard/me" || path.startsWith("/dashboard/me/") || path.startsWith("/dashboard/me?");

// Only same-origin paths: an absolute or protocol-relative callbackUrl ("https://evil.example", "//evil.example") would make
// login an open redirector. `under`: a sign-in page of one product only returns to that product's pages (Yaad: /dashboard/me).
export function safeCallback(raw: string | null, fallback: string, under?: string): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  if (under && raw !== under && !raw.startsWith(under + "/") && !raw.startsWith(under + "?")) return fallback;
  return raw;
}

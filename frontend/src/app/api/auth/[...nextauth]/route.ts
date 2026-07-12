import { handlers } from "@/lib/auth";

// NextAuth's CSRF/session/callback routes must never be cached — a cached
// /api/auth/csrf response served to a different request would desync the
// CSRF token from the credentials POST, causing signIn() to silently drop
// the request body (empty email/password reaching authorize()).
export const dynamic = "force-dynamic";

export const { GET, POST } = handlers;

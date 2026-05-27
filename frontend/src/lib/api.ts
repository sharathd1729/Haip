import axios from "axios";
import { getSession, signOut } from "next-auth/react";

// Ensure base URL always ends with /api/v1 regardless of how NEXT_PUBLIC_API_URL is set.
// e.g. "https://72.61.228.243" → "https://72.61.228.243/api/v1"
// e.g. "https://72.61.228.243/api/v1" → stays as-is
const _raw = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const API_BASE = _raw.endsWith("/api/v1") ? _raw : `${_raw}/api/v1`;

const api = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use(async (config) => {
  const session = await getSession();
  if (session?.accessToken) {
    config.headers.Authorization = `Bearer ${session.accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const originalRequest = error.config;

    // On 401: the JWT callback may have already refreshed the token — retry once.
    // Guard with _retry to prevent infinite loops.
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      // Re-fetch session — the JWT callback auto-refreshes if token was stale
      const session = await getSession();

      if (!session || (session as any).error === "RefreshAccessTokenError") {
        // Refresh failed or session gone — sign out cleanly
        signOut({ callbackUrl: "/login" });
        return Promise.reject(error);
      }

      // Attach the fresh token and retry the original request
      if ((session as any).accessToken) {
        originalRequest.headers = originalRequest.headers ?? {};
        originalRequest.headers.Authorization = `Bearer ${(session as any).accessToken}`;
      }
      return api(originalRequest);
    }

    return Promise.reject(error);
  }
);

export default api;

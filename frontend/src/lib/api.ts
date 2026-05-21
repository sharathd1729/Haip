import axios from "axios";
import { getSession } from "next-auth/react";

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
    // Don't auto-redirect on 401 — let components handle empty/error states.
    // The session middleware protects routes; a stale token just means empty data.
    return Promise.reject(error);
  }
);

export default api;

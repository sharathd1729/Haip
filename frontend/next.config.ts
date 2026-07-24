import type { NextConfig } from "next";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  // Standalone output bundles only what's needed — makes Docker images ~60% smaller
  output: "standalone",
  experimental: {},
  async rewrites() {
    return [
      {
        // Proxy all /api/v1/* requests to the FastAPI backend.
        // This eliminates CORS entirely — the browser only ever talks to the
        // same origin (genhaip.com). Set BACKEND_URL in your deployment env.
        source: "/api/v1/:path*",
        destination: `${BACKEND_URL}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        // The service worker file itself must never be cached -- browsers
        // (and any CDN/proxy in front of this app) only check for a new
        // sw.js when this request actually reaches the origin. Confirmed
        // live: mobile users stuck on an old app version because nothing
        // forced revalidation of this file.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        ],
      },
      {
        source: "/manifest.json",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        ],
      },
    ];
  },
};

export default nextConfig;

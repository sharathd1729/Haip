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
};

export default nextConfig;

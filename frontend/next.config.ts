import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output bundles only what's needed — makes Docker images ~60% smaller
  output: "standalone",
  experimental: {},
};

export default nextConfig;

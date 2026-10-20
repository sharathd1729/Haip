import type { NextConfig } from "next";

// Every request is a client website, chosen by hostname in src/middleware.ts. Runtime settings (read on the server,
// never baked into the client bundle): HAIP_API_URL (internal API, e.g. http://haip_api:8000), SITES_REVALIDATE_SECRET.
const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: { root: __dirname },
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "X-Frame-Options", value: "SAMEORIGIN" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};

export default nextConfig;

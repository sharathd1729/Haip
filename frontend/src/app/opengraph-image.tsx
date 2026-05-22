import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "HAIP — Hospitality AI Intelligence Platform";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OGImage() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#0B1F3A",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "sans-serif",
        }}
      >
        {/* Logo mark */}
        <div
          style={{
            width: 100,
            height: 100,
            borderRadius: 24,
            background: "#14b8a6",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: 32,
          }}
        >
          <span style={{ color: "#0B1F3A", fontSize: 56, fontWeight: 900 }}>H</span>
        </div>

        {/* Brand name */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <span style={{ color: "#ffffff", fontSize: 72, fontWeight: 800, letterSpacing: -2 }}>
            HAIP
          </span>
        </div>

        {/* Tagline */}
        <p style={{ color: "#94a3b8", fontSize: 28, margin: 0, textAlign: "center", maxWidth: 700 }}>
          Hospitality AI Intelligence Platform
        </p>

        <p style={{ color: "#14b8a6", fontSize: 22, marginTop: 16, textAlign: "center" }}>
          Unified inbox · AI call intelligence · Guest CRM
        </p>

        {/* Domain */}
        <div
          style={{
            position: "absolute",
            bottom: 40,
            color: "#475569",
            fontSize: 20,
          }}
        >
          www.genhaip.com
        </div>
      </div>
    ),
    { ...size }
  );
}

"use client";
// One map for Ops GPS (the live vehicle map and the small map on a trip file). MapLibre GL with free OpenStreetMap raster
// tiles: no API key, no account. MapLibre is loaded in an effect (it needs the browser and WebGL), so the server render and
// the first client render are the same empty frame. Line colours are read from the theme tokens at runtime; markers are
// plain elements styled with the same tokens.
import { useEffect, useRef, useState } from "react";
import type { Map as MlMap, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { cn } from "@/lib/utils";

export interface MapMarker {
  id: string; lat: number; lng: number; label: string; title: string; tone: "moving" | "parked" | "alert";
  onClick?: () => void;
}
export interface MapLine { id: string; coords: [number, number][]; kind: "track" | "planned" | "detour" }

const TONE = {
  moving: "bg-primary",
  parked: "bg-[var(--haip-fg-muted)]",
  alert: "bg-[var(--haip-status-danger-fg)]",
};
const LINE_TOKEN = { track: "--primary", planned: "--haip-accent", detour: "--haip-status-warning-fg" } as const;
const OSM_STYLE = {
  version: 8 as const,
  sources: {
    osm: {
      type: "raster" as const, tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster" as const, source: "osm" }],
};
const INDIA: [number, number] = [77.59, 12.97];

function token(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function GpsMap({ markers = [], lines = [], className, label }: {
  markers?: MapMarker[]; lines?: MapLine[]; className?: string; label: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const pins = useRef<Marker[]>([]);
  const fitted = useRef(false);
  const lib = useRef<typeof import("maplibre-gl") | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let gone = false;
    import("maplibre-gl").then(ml => {
      if (gone || !box.current) return;
      try {
        lib.current = ml;
        const m = new ml.Map({ container: box.current, style: OSM_STYLE, center: INDIA, zoom: 6, attributionControl: { compact: true } });
        m.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
        m.on("load", () => { if (!gone) setReady(true); });
        map.current = m;
      } catch {
        setFailed(true); // no WebGL on this device
      }
    }).catch(() => setFailed(true));
    return () => { gone = true; pins.current.forEach(p => p.remove()); map.current?.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current, ml = lib.current;
    if (!ready || !m || !ml) return;
    for (const kind of ["planned", "detour", "track"] as const) {
      const id = `gps-${kind}`;
      const data = {
        type: "FeatureCollection" as const,
        features: lines.filter(l => l.kind === kind && l.coords.length > 1).map(l => ({
          type: "Feature" as const, properties: {},
          geometry: { type: "LineString" as const, coordinates: l.coords.map(([la, lo]) => [lo, la]) },
        })),
      };
      const src = m.getSource(id) as { setData?: (d: unknown) => void } | undefined;
      if (src?.setData) src.setData(data);
      else {
        m.addSource(id, { type: "geojson", data });
        m.addLayer({
          id, type: "line", source: id, layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": token(LINE_TOKEN[kind], "gray"),
            "line-width": kind === "track" ? 4 : 3,
            ...(kind === "track" ? {} : { "line-dasharray": [2, 1.5] }),
          },
        });
      }
    }
    pins.current.forEach(p => p.remove());
    pins.current = markers.map(mk => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = cn("grid size-10 place-items-center rounded-full border-2 border-white text-[12px] font-bold text-white shadow-md", TONE[mk.tone]);
      el.textContent = mk.label;
      el.setAttribute("aria-label", mk.title);
      el.title = mk.title;
      if (mk.onClick) el.addEventListener("click", mk.onClick);
      return new ml.Marker({ element: el }).setLngLat([mk.lng, mk.lat]).addTo(m);
    });
    const pts = [...markers.map(mk => [mk.lat, mk.lng] as [number, number]), ...lines.flatMap(l => l.coords)];
    if (!fitted.current && pts.length) {
      const b = new ml.LngLatBounds();
      pts.forEach(([la, lo]) => b.extend([lo, la]));
      m.fitBounds(b, { padding: 48, maxZoom: 14, duration: 0 });
      fitted.current = true;
    }
  }, [ready, markers, lines]);

  if (failed) {
    return (
      <div className={cn("grid place-items-center rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-4 text-center text-[14px] text-[var(--haip-fg-muted)]", className)}>
        The map could not load on this device. The list below still shows every vehicle.
      </div>
    );
  }
  return <div ref={box} role="region" aria-label={label} className={cn("overflow-hidden rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)]", className)} />;
}

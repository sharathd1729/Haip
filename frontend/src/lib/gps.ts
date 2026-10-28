// Ops GPS (backend migration 181): the shapes GET /ops/gps/live, /ops/gps/files/{id}/track and /ops/gps/settings return,
// and the small word rules the map, the trip file and the settings page share. Alert rules live on the server
// (services/gps_alerts.py); nothing here decides what is a problem.

export type VehicleState = "moving" | "parked" | "no_signal" | "no_tracker";

export interface GpsAlert { id: string; kind: string; title: string; severity: string; summary: string | null; created_at: string | null }
export interface LiveVehicle {
  property_id: string; name: string; device_id: string | null; lat: number | null; lng: number | null;
  speed_kmh: number | null; heading: number | null; ignition: boolean | null; last_seen_at: string | null;
  minutes_since: number | null; state: VehicleState; file_id: string | null; guest_name: string | null; alerts: GpsAlert[];
}
export interface GpsLive { vehicles: LiveVehicle[]; at: string }

export interface RoutePoint { lat: number; lng: number; name?: string | null; stop?: boolean }
export interface PlannedRoute {
  points: RoutePoint[]; night_driving_ok: boolean;
  detours?: { points: [number, number][]; reason: string; open: boolean }[];
}
export interface GpsTrack {
  file_id: string; points: [number, number][]; planned_route: PlannedRoute | null;
  gps_km: number | null; tracker_odometer_km: number | null; odometer_km: number | null;
  first_at: string | null; last_at: string | null;
}

export interface GpsProviderInfo {
  key: string; label: string; shape: "push" | "pull"; enabled: boolean; fields: string[]; secret_fields: string[];
  blocked_reason: string | null;
}
export interface GpsSettings {
  providers: GpsProviderInfo[]; provider: string | null; status: string; base_url: string | null; username: string | null;
  has_password: boolean; has_webhook_secret: boolean; webhook_url: string; last_error: string | null;
  last_health_at: string | null; rules: Record<string, unknown>; webhook_secret?: string | null;
}
export interface GpsDevice {
  id: string; provider: string; external_id: string; label: string | null; property_id: string | null;
  property_name: string | null; active: boolean; last_seen_at: string | null;
  last_position: { lat: number; lng: number; speed_kmh: number | null; ignition: boolean | null } | null;
}

export const STATE_WORDS: Record<VehicleState, string> = {
  moving: "Moving", parked: "Parked", no_signal: "No signal yet", no_tracker: "No tracker",
};

/** "just now" | "4 min ago" | "2 h ago" | "3 days ago" from the server's minute count. */
export function lastSeen(minutes: number | null): string {
  if (minutes === null) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

/** One line under a vehicle: what it is doing right now, in plain words. */
export function vehicleLine(v: LiveVehicle): string {
  if (v.state === "no_tracker") return v.file_id ? "On a trip, no tracker mapped" : "No tracker mapped";
  if (v.state === "no_signal") return "Tracker added, no position yet";
  const speed = v.state === "moving" && v.speed_kmh !== null ? ` at ${Math.round(v.speed_kmh)} km/h` : "";
  return `${STATE_WORDS[v.state]}${speed} · ${lastSeen(v.minutes_since)}`;
}

/** GPS km beside the odometer km on the trip file. The odometer photo bills; GPS is only a cross-check. */
export function distanceCheck(t: Pick<GpsTrack, "gps_km" | "odometer_km">): string | null {
  if (t.gps_km === null) return null;
  if (t.odometer_km === null) return `GPS so far: ${t.gps_km.toLocaleString("en-IN")} km`;
  const gap = Math.abs(t.gps_km - t.odometer_km);
  const pct = t.odometer_km > 0 ? Math.round((gap / t.odometer_km) * 100) : 0;
  return `GPS ${t.gps_km.toLocaleString("en-IN")} km · odometer ${t.odometer_km.toLocaleString("en-IN")} km` +
    (pct >= 10 ? ` (${pct}% apart: check the photos)` : "");
}

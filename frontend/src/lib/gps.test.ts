import { describe, expect, it } from "vitest";
import { distanceCheck, lastSeen, vehicleLine, type LiveVehicle } from "./gps";

const v = (patch: Partial<LiveVehicle>): LiveVehicle => ({
  property_id: "p", name: "Ratha 1", device_id: "d", lat: 12.9, lng: 77.6, speed_kmh: 52.4, heading: null, ignition: true,
  last_seen_at: null, minutes_since: 2, state: "moving", file_id: null, guest_name: null, alerts: [], ...patch,
});

describe("gps words", () => {
  it("says how long ago", () => {
    expect([lastSeen(null), lastSeen(0), lastSeen(4), lastSeen(130), lastSeen(4000)]).toEqual(
      ["never", "just now", "4 min ago", "2 h ago", "3 days ago"]);
  });
  it("describes a vehicle", () => {
    expect(vehicleLine(v({}))).toBe("Moving at 52 km/h · 2 min ago");
    expect(vehicleLine(v({ state: "parked", minutes_since: 30 }))).toBe("Parked · 30 min ago");
    expect(vehicleLine(v({ state: "no_tracker", file_id: "f" }))).toBe("On a trip, no tracker mapped");
  });
  it("cross-checks GPS against the odometer", () => {
    expect(distanceCheck({ gps_km: null, odometer_km: 50 })).toBeNull();
    expect(distanceCheck({ gps_km: 48, odometer_km: 50 })).toBe("GPS 48 km · odometer 50 km");
    expect(distanceCheck({ gps_km: 30, odometer_km: 50 })).toContain("40% apart");
    expect(distanceCheck({ gps_km: 12.5, odometer_km: null })).toBe("GPS so far: 12.5 km");
  });
});

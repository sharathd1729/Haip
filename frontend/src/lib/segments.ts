// One product experience per business type (owner, 1 Nov 2026: the portal is segment-based). The ONE place that says what a
// workspace's screens call things, which sections they show and what a booking card carries. Screens read `useSegment()` /
// `segmentFor()`; they never test the business type themselves. Caravan keeps the words and sections it has today.
import { useBusinessType, type BusinessType } from "@/components/providers/WorkspaceProvider";

export type SegmentKey = "caravan" | "villa" | "homestay" | "hotel" | "property";
/** What a booking card can show; each segment lists the ones it carries, in order. */
export type CardField = "dates" | "nights" | "guests" | "unit" | "route" | "km" | "driver" | "caretaker" | "deposit" | "balance";

export interface Segment {
  key: SegmentKey;
  unit: { one: string; many: string; One: string; Many: string };
  booking: { one: string; many: string };            // trip | stay
  start: string; end: string;                         // pickup → drop | check-in → check-out
  timing: string;                                     // the strip's and calendar's one-line rule
  allUnits: string;                                   // picker option that shows every unit
  whichUnit: string;                                  // an event or booking that names no unit
  notChosen: string;                                  // a booking parked on the placeholder unit
  nobodyIn: string;                                   // "Staying now" with nobody in
  syncExample: string;                                // Settings > Calendar sync keyword example
  startLabel: string; endLabel: string;               // booking detail fact labels
  dayUse: string;                                     // a booking that starts and ends the same day
  staying: { heading: string; count: (n: number) => string };   // the "Staying now" group on Bookings
  notesHint: string;                                  // staff notes placeholder on a booking
  unitTint: boolean;                                  // one soft colour per unit (only worth it for a couple of units)
  sections: {
    bookings: { strip: boolean; stripCollapsedAbove: number };
    calendar: { channelFilter: boolean; rentalwiseSync: boolean };
    bookingDetail: { route: boolean; kmAndDriver: boolean; caretaker: boolean; deposit: boolean };
  };
  card: CardField[];
}

const words = (one: string, many: string) => ({ one, many, One: one[0].toUpperCase() + one.slice(1), Many: many[0].toUpperCase() + many.slice(1) });

const STAY_BASE = {
  booking: { one: "stay", many: "stays" }, start: "check-in", end: "check-out", timing: "check-in afternoon → check-out morning",
  nobodyIn: "Nobody is staying right now",
  startLabel: "Check-in", endLabel: "Check-out", dayUse: "day use",
  staying: { heading: "Staying now", count: (n: number) => `${n} staying` },
  notesHint: "Arrival time, food, anything the caretaker should know.", unitTint: false,
  sections: {
    bookings: { strip: true, stripCollapsedAbove: 6 },
    calendar: { channelFilter: true, rentalwiseSync: false },
    bookingDetail: { route: false, kmAndDriver: false, caretaker: true, deposit: true },
  },
  card: ["dates", "nights", "guests", "unit", "caretaker", "deposit", "balance"] as CardField[],
};

// rentalwise: the old RentalWise sync button stays for the businesses that had it; villa businesses never used it (owner mock-up).
const stay = (key: SegmentKey, one: string, many: string, example: string, rentalwise = true): Segment => ({
  ...STAY_BASE, key, unit: words(one, many), allUnits: `All ${many}`, whichUnit: `Which ${one}?`,
  notChosen: `Unassigned (${one} not chosen yet)`, syncExample: example,
  sections: { ...STAY_BASE.sections, calendar: { ...STAY_BASE.sections.calendar, rentalwiseSync: rentalwise } },
});

export const SEGMENTS: Record<SegmentKey, Segment> = {
  caravan: {
    key: "caravan", unit: words("vehicle", "vehicles"), booking: { one: "trip", many: "trips" }, start: "pickup", end: "drop",
    timing: "noon to noon", allUnits: "All vehicles", whichUnit: "Which vehicle?", notChosen: "Unassigned (vehicle not chosen yet)",
    nobodyIn: "Nobody is on a trip right now", syncExample: "white, white ratha",
    startLabel: "Pickup (check-in)", endLabel: "Drop (check-out)", dayUse: "day trip",
    staying: { heading: "On a trip now", count: n => `${n} on a trip` },
    notesHint: "Which caravan: Black Ratha / White Ratha. Anything the team should know.", unitTint: true,
    sections: {
      bookings: { strip: true, stripCollapsedAbove: 6 },
      calendar: { channelFilter: false, rentalwiseSync: false },
      bookingDetail: { route: true, kmAndDriver: true, caretaker: false, deposit: true },
    },
    card: ["dates", "guests", "unit", "route", "km", "driver", "balance"],
  },
  villa: stay("villa", "villa", "villas", "blue dome, blue", false),
  homestay: stay("homestay", "property", "properties", "garden room, garden"),
  hotel: stay("hotel", "room", "rooms", "deluxe 101, 101"),
  property: stay("property", "property", "properties", "garden room, garden"),
};

// shortcut: BusinessType has 4 values today; service apartment, farmhouse, resort and travel agency get their own entry here
// (and in this map) when the backend sends them. Until then, and while the workspace is loading, a business is a "property".
const BY_TYPE: Record<BusinessType, SegmentKey> = { caravan: "caravan", villa_resort: "villa", homestay: "homestay", hotel: "hotel" };

export function segmentFor(type: BusinessType | null | undefined): Segment {
  return SEGMENTS[(type && BY_TYPE[type]) || "property"];
}

export function useSegment(): Segment {
  return segmentFor(useBusinessType());
}

/** The strip / calendar row label of the placeholder unit that holds bookings no unit was chosen for. */
export function placeholderLabel(seg: Segment): string {
  return seg.key === "caravan" ? "Unassigned" : seg.whichUnit;
}

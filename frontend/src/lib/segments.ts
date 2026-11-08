// One product experience per business type (owner, 1 Nov 2026: the portal is segment-based). The ONE place that says what a
// workspace's screens call things, which sections they show and what a booking card carries. Screens read `useSegment()` /
// `segmentFor()`; they never test the business type themselves. Caravan keeps the words and sections it has today.
import { useBusinessType, type BusinessType } from "@/components/providers/WorkspaceProvider";

export type SegmentKey = "caravan" | "villa" | "farmhouse" | "rental" | "homestay" | "hotel" | "property";
/** The ops flow behind a segment (backend ops_pack_catalog.FLOWS): trip, whole_unit or room; null = no ops pack. */
export type OpsFlow = "trip" | "whole_unit" | "room";
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
  /** Ops screens: the flow, whether it has a fleet (Fleet + Map tabs), whether self check-in is offered per property. */
  ops: { flow: OpsFlow | null; fleet: boolean; selfCheckIn: boolean };
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
const stay = (key: SegmentKey, one: string, many: string, example: string, flow: OpsFlow | null, rentalwise = true): Segment => ({
  ...STAY_BASE, key, unit: words(one, many), allUnits: `All ${many}`, whichUnit: `Which ${one}?`,
  notChosen: `Unassigned (${one} not chosen yet)`, syncExample: example,
  sections: { ...STAY_BASE.sections, calendar: { ...STAY_BASE.sections.calendar, rentalwiseSync: rentalwise } },
  ops: { flow, fleet: false, selfCheckIn: flow === "whole_unit" },
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
    ops: { flow: "trip", fleet: true, selfCheckIn: false },
  },
  villa: stay("villa", "villa", "villas", "blue dome, blue", "whole_unit", false),
  farmhouse: stay("farmhouse", "farmhouse", "farmhouses", "mango barn, barn", "whole_unit", false),
  rental: stay("rental", "apartment", "apartments", "flat 2b, 2b", "whole_unit"),
  homestay: stay("homestay", "property", "properties", "garden room, garden", "whole_unit"),
  hotel: stay("hotel", "room", "rooms", "deluxe 101, 101", "room"),
  property: stay("property", "property", "properties", "garden room, garden", null),
};

// Every business type the backend offers (ops_pack_catalog.BUSINESS_TYPES) and its experience. "villa" / "caravan_rv" are older
// stored values. Unknown, or while the workspace is loading, a business is a plain "property" (no ops pack).
const BY_TYPE: Record<BusinessType, SegmentKey> = {
  caravan: "caravan", villa_resort: "villa", farmhouse: "farmhouse", vacation_rental: "rental",
  homestay: "homestay", hotel: "hotel", resort: "hotel", guesthouse: "hotel",
};
const OLDER: Record<string, SegmentKey> = { villa: "villa", caravan_rv: "caravan" };

/** Sign-up and Settings > Workspace: what each business type is called (same order as the backend). */
export const BUSINESS_TYPE_OPTIONS: { value: BusinessType; label: string; emoji: string }[] = [
  { value: "caravan", label: "Caravans and campervans", emoji: "🚐" },
  { value: "villa_resort", label: "Villas", emoji: "🏝️" },
  { value: "farmhouse", label: "Farmhouses", emoji: "🌾" },
  { value: "vacation_rental", label: "Vacation rentals and apartments", emoji: "🏢" },
  { value: "homestay", label: "Homestays", emoji: "🏡" },
  { value: "hotel", label: "Boutique hotels", emoji: "🏨" },
  { value: "resort", label: "Resorts", emoji: "🌴" },
  { value: "guesthouse", label: "Guesthouses", emoji: "🛏️" },
];

export function segmentFor(type: BusinessType | string | null | undefined): Segment {
  const key = !type ? undefined : Object.hasOwn(BY_TYPE, type) ? BY_TYPE[type as BusinessType] : Object.hasOwn(OLDER, type) ? OLDER[type] : undefined;
  return SEGMENTS[key || "property"];
}

/** Business types whose segment runs an ops pack (the nav's Ops item). */
export const OPS_BUSINESS_TYPES: string[] = [...Object.keys(BY_TYPE), ...Object.keys(OLDER)]
  .filter(t => segmentFor(t).ops.flow !== null);

export function useSegment(): Segment {
  return segmentFor(useBusinessType());
}

/** The strip / calendar row label of the placeholder unit that holds bookings no unit was chosen for. */
export function placeholderLabel(seg: Segment): string {
  return seg.key === "caravan" ? "Unassigned" : seg.whichUnit;
}

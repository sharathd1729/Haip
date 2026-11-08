"""Ops packs (Ops 2, gap 7 "every segment, one design"). Three base FLOWS cover every hospitality segment, because what
really differs is how many units turn over a day and who meets the guest:

  trip        a vehicle or experience handed over and taken back (caravans, campervans). Machine: ops_trip_service.
  whole_unit  one booking takes the whole place (villas, farmhouses, vacation rentals, apartments, whole-home homestays).
              Machine: ops_stay_service. May be self check-in: nobody meets the guest (ops_self_check_in).
  room        many rooms, many arrivals a day. Runs on the stay machine (one file per booking: room ready -> check-in ->
              staying -> check-out inspection -> settle) until the daily room board ("Ops 2e") is built.

A PACK is one segment's data on top of its flow: unit and file words, steps, states, default checklists, staff duties,
in-stay issue types, paperwork, add-on suggestions and automatic-message timings. ops_pack_seed copies the defaults into the
business's own rows (ops_checklist_templates, ops_settings.pack_config) once, never over an edit; the business edits them
there (checklists per property too). A business's category (tenants.business_type, chosen at sign-up or in Settings) picks
its pack.

caravan_rv and villa keep exactly the keys and values they had (Ratha, Jade): tests/fixtures/ops_packs pins them.
"""

STEPS = ("get_ready", "hand_over", "during", "take_back", "settle", "done")

# The 12-point dispatch gate, condensed from RathaOS §15.1 (Ratha's own Maintenance Checklist SOP replaces it when shared).
# source: staff = a helper photo, system = HAIP data, manager = ticked by the manager.
_CARAVAN_READINESS = [
    ("tyres", "Tyres, brakes, fluids, lights", True, "staff", True),
    ("electrical", "Electrical, sockets, UPS, generator", True, "staff", True),
    ("ac", "AC and cooling", True, "staff", True),
    ("water", "Water, leak test, shower, hot water, drainage", True, "staff", True),
    ("interior", "Interior: glass, curtains, bed, seats", False, "staff", True),
    ("safety", "First aid, fire extinguisher, documents onboard", True, "staff", True),
    ("licence", "Driver HMV licence valid, briefed", True, "manager", False),
    ("route", "Route, height, parking, permits checked", True, "manager", False),
    ("partner", "Partner site reconfirmed", False, "manager", False),
    ("inventory", "Inventory and add-ons at par", False, "staff", True),
    ("payment", "Payment, deposit, agreement signed", True, "system", False),
    ("guests", "Guest list, pickup, emergency contact", True, "manager", False),
]

# Villa pack (phase 4, Jade). Ready to welcome = the gate before check-in; Check-out inspection = the same zones after the
# guest leaves, compared with the arrival photos; a mid-stay clean every 3rd day for stays of 4+ nights.
_VILLA_READY = [
    ("pool", "Pool cleaned", True, "staff", True),
    ("chlorine", "Pool water tested: chlorine and pH", True, "staff", True),
    ("bedrooms", "Bedrooms made up", True, "staff", True),
    ("ac", "AC and hot water working", True, "staff", True),
    ("wifi", "Wi-Fi working", False, "staff", True),
    ("garden", "Garden and outdoor seating", False, "staff", True),
    ("kitchen", "Gas and kitchen ready", True, "staff", True),
    ("welcome", "Welcome kit in place", False, "staff", True),
    ("linen", "Towels and linen at par", False, "staff", True),
    ("payment", "Payment received", False, "system", False),
    ("guests", "Guest name and party size", False, "system", False),
]
_VILLA_INSPECT = [
    ("pool", "Pool", False, "staff", True),
    ("bedrooms", "Bedrooms", False, "staff", True),
    ("ac", "AC and hot water", False, "staff", True),
    ("garden", "Garden and outdoor seating", False, "staff", True),
    ("kitchen", "Gas and kitchen", False, "staff", True),
    ("linen", "Towels and linen counted", False, "staff", True),
    ("damage", "Damage or breakage", True, "staff", True),
    ("missing", "Missing items (remotes, kitchenware, towels)", True, "staff", True),
]

# Vacation rentals and apartments: a cleaning crew turns the place over; usually nobody meets the guest (self check-in).
_RENTAL_READY = [
    ("clean", "Cleaned: floors, surfaces, bins emptied", True, "staff", True),
    ("beds", "Beds made with fresh linen", True, "staff", True),
    ("bathroom", "Bathroom cleaned, towels and toiletries out", True, "staff", True),
    ("kitchen", "Kitchen and appliances clean and working", True, "staff", True),
    ("ac", "AC and hot water working", True, "staff", True),
    ("wifi", "Wi-Fi working", False, "staff", True),
    ("access", "Lock, code or key box working", True, "staff", True),
    ("consumables", "Consumables restocked (tea, coffee, soap, tissues)", False, "staff", True),
    ("payment", "Payment received", False, "system", False),
    ("guests", "Guest name and party size", False, "system", False),
]
_RENTAL_INSPECT = [
    ("kitchen", "Kitchen and appliances", False, "staff", True),
    ("beds", "Bedrooms", False, "staff", True),
    ("bathroom", "Bathroom", False, "staff", True),
    ("linen", "Towels and linen counted", False, "staff", True),
    ("damage", "Damage or breakage", True, "staff", True),
    ("missing", "Missing items (remotes, keys, kitchenware)", True, "staff", True),
    ("access", "Key returned or code changed", True, "staff", False),
]
# Homestays: the host meets the guest; the whole home or rooms in it.
_HOMESTAY_READY = [
    ("rooms", "Rooms made up", True, "staff", True),
    ("bathroom", "Bathroom clean, hot water working", True, "staff", True),
    ("linen", "Towels and linen out", False, "staff", True),
    ("wifi", "Wi-Fi working", False, "staff", True),
    ("meals", "Home meals planned (if booked)", False, "manager", False),
    ("directions", "Directions and arrival time shared", False, "manager", False),
    ("register", "Guest register ready (Form B)", False, "manager", False),
    ("payment", "Payment received", False, "system", False),
    ("guests", "Guest name and party size", False, "system", False),
]
_HOMESTAY_INSPECT = [
    ("rooms", "Rooms", False, "staff", True),
    ("bathroom", "Bathroom", False, "staff", True),
    ("damage", "Damage or breakage", True, "staff", True),
    ("missing", "Missing items", True, "staff", True),
]
# Boutique hotels, resorts, guesthouses: the front desk meets the guest; one file per room booking until the room board.
_ROOM_READY = [
    ("room", "Room cleaned, bed made", True, "staff", True),
    ("bathroom", "Bathroom cleaned, towels and toiletries out", True, "staff", True),
    ("ac", "AC, TV and remote working", True, "staff", True),
    ("hot_water", "Hot water working", True, "staff", False),
    ("amenities", "Minibar and amenities at par", False, "staff", True),
    ("inspected", "Room inspected by the supervisor", False, "manager", False),
    ("payment", "Payment received", False, "system", False),
    ("guests", "Guest name and party size", False, "system", False),
]
_ROOM_INSPECT = [
    ("room", "Room", False, "staff", True),
    ("bathroom", "Bathroom", False, "staff", True),
    ("minibar", "Minibar used (charge it)", False, "staff", True),
    ("damage", "Damage or breakage", True, "staff", True),
    ("missing", "Missing items (towels, remotes, hair dryer)", True, "staff", True),
]

# The stay machine's states (ops_stay_service); every whole_unit and room pack uses them.
_STAY_STATES = {"preparing": 0, "ready": 1, "staying": 2, "checked_out": 3, "settling": 4, "closed": 5, "cancelled": 5}
_STAY_STEPS = ("Get ready", "Welcome", "Staying", "Check-out", "Settle", "Done")

# Automatic-message timings. when: before_start (hours before check-in / pickup), after_end (hours after return /
# check-out), stay_day (local day N of the stay). built=False: stored for a card not built yet (pre-arrival = Ops 2d).
_TRIP_MESSAGES = {
    "crew_brief": {"when": "before_start", "hours": 72, "to": "staff", "built": True},
    "helper_chase": {"when": "before_start", "hours": 24, "to": "staff", "built": True},
    "guest_pretrip": {"when": "before_start", "hours": 24, "to": "guest", "built": True},
    "deposit_nudge": {"when": "after_end", "hours": 24, "to": "managers", "built": True},
    "midstay_check": {"when": "stay_day", "day": 2, "to": "guest", "built": True},
}
_STAY_MESSAGES = {
    "pre_arrival_form": {"when": "before_start", "hours": 72, "to": "guest", "built": False},
    "pre_arrival": {"when": "before_start", "hours": 24, "to": "guest", "built": False},
    "midstay_check": {"when": "stay_day", "day": 2, "to": "guest", "built": True},
}


def _items(rows: list) -> list[dict]:
    return [
        {"key": k, "label": label, "critical": crit, "source": src, "photo": photo} for k, label, crit, src, photo in rows
    ]


def _issues(rows: list) -> list[dict]:
    return [{"key": k, "label": label, "category": cat} for k, label, cat in rows]


def _addons(rows: list) -> list[dict]:
    return [{"key": k, "label": label} for k, label in rows]


PACKS: dict[str, dict] = {
    "caravan_rv": {
        "label": "Caravan / RV",
        "unit_word": "vehicle",
        "file_word": "trip",
        "step_names": (
            "Set up",
            "Prepare",
            "Dispatch",
            "On the road",
            "Return & bill",
            "Done",
        ),
        # state -> step index (0-based into STEPS); cancelled shows as done
        "states": {
            "handed_over": 0,
            "crew_assigned": 1,
            "readiness": 1,
            "dispatch_ready": 2,
            "on_trip": 3,
            "returned": 4,
            "closed": 5,
            "cancelled": 5,
        },
        "first_state": "handed_over",
        "cancellable": ("handed_over", "crew_assigned", "readiness", "dispatch_ready"),
        "flow": "trip",
        "flows": ("trip",),
        "host_label": "Driver",
        "duties": ("driver", "maintenance", "ops_manager"),
        "issue_types": _issues(
            [
                ("breakdown", "Breakdown", "vehicle"),
                ("ac", "AC not cooling", "ac"),
                ("water", "Water, shower or drainage", "plumbing"),
                ("route", "Route, parking or permit", "route"),
            ]
        ),
        "paperwork": ("Guest ID", "Driving licence (self-drive)", "Form C for foreign guests"),
        "addons": _addons([("extra_km", "Extra km"), ("bbq", "BBQ"), ("camping_kit", "Camping kit")]),
        "auto_messages": _TRIP_MESSAGES,
        "midstay_clean": None,
        "self_check_in": False,
        "checklists": {
            "readiness": {
                "name": "Ready to leave",
                "items": [
                    {
                        "key": k,
                        "label": label,
                        "critical": crit,
                        "source": src,
                        "photo": photo,
                    }
                    for k, label, crit, src, photo in _CARAVAN_READINESS
                ],
            },
            # On return the helper photographs the same zones again ("return ac"); each is compared with its handover
            # photo (ops_return_check). Not a gate: a difference is a manager flag about the deposit.
            "return": {
                "name": "Back from the trip",
                "items": [
                    {
                        "key": k,
                        "label": label,
                        "critical": False,
                        "source": "staff",
                        "photo": True,
                    }
                    for k, label, _crit, src, photo in _CARAVAN_READINESS
                    if photo and src == "staff"
                ],
            },
        },
    },
    "villa": {
        "label": "Villa",
        "unit_word": "villa",
        "file_word": "stay",
        "step_names": _STAY_STEPS,
        "states": dict(_STAY_STATES),
        "first_state": "preparing",
        "cancellable": ("preparing", "ready"),
        "flow": "whole_unit",
        "flows": ("whole_unit",),
        "host_label": "Caretaker",
        "duties": ("caretaker", "housekeeping", "fnb", "maintenance", "ops_manager"),
        "issue_types": _issues(
            [
                ("pool", "Pool", "pool"),
                ("power", "Power cut", "power"),
                ("gas", "Gas", "gas"),
                ("ac", "AC", "ac"),
                ("wifi", "Wi-Fi", "wifi"),
            ]
        ),
        "paperwork": ("ID for every adult", "Form C for foreign guests"),
        "addons": _addons(
            [("cook", "Cook and meals"), ("bbq", "BBQ"), ("decor", "Decor"), ("early_check_in", "Early check-in")]
        ),
        "auto_messages": _STAY_MESSAGES,
        "midstay_clean": {"every_days": 3, "min_nights": 4},
        "self_check_in": False,
        "checklists": {
            "readiness": {"name": "Ready to welcome", "items": _items(_VILLA_READY)},
            "inspection": {"name": "Check-out inspection", "items": _items(_VILLA_INSPECT)},
        },
    },
}


def _stay_pack(label: str, unit: str, steps: tuple, ready: dict, inspect: dict, **data) -> dict:
    return {
        "label": label,
        "unit_word": unit,
        "file_word": "stay",
        "step_names": steps,
        "states": dict(_STAY_STATES),
        "first_state": "preparing",
        "cancellable": ("preparing", "ready"),
        "auto_messages": _STAY_MESSAGES,
        **data,
        "checklists": {"readiness": ready, "inspection": inspect},
    }


PACKS["vacation_rental"] = _stay_pack(
    "Vacation rental / apartment",
    "apartment",
    _STAY_STEPS,
    {"name": "Ready for the guest", "items": _items(_RENTAL_READY)},
    {"name": "Check-out inspection", "items": _items(_RENTAL_INSPECT)},
    flow="whole_unit",
    flows=("whole_unit",),
    host_label="Cleaner",
    duties=("housekeeping", "maintenance", "ops_manager"),
    issue_types=_issues(
        [("access", "Lock or code", "access"), ("wifi", "Wi-Fi", "wifi"), ("appliance", "Appliance", "appliance")]
    ),
    paperwork=("ID for every adult", "Form C for foreign guests"),
    addons=_addons(
        [("early_check_in", "Early check-in"), ("late_check_out", "Late check-out"), ("midstay_clean", "Mid-stay clean")]
    ),
    midstay_clean=None,  # turnover by the cleaning crew; a mid-stay clean is an add-on the guest buys
    self_check_in=True,  # the default for a new rental property; each property sets its own
)
PACKS["homestay"] = _stay_pack(
    "Homestay",
    "property",
    _STAY_STEPS,
    {"name": "Ready for the guest", "items": _items(_HOMESTAY_READY)},
    {"name": "Check-out check", "items": _items(_HOMESTAY_INSPECT)},
    flow="whole_unit",
    flows=("whole_unit", "room"),  # a homestay that lets rooms picks room in ops_settings.pack_config
    host_label="Host",
    duties=("caretaker", "housekeeping", "fnb", "ops_manager"),
    issue_types=_issues(
        [("hot_water", "Hot water", "hot_water"), ("food", "Food", "food"), ("directions", "Directions", "route")]
    ),
    paperwork=("ID for every adult", "Form C for foreign guests", "Form B guest register"),
    addons=_addons([("home_meals", "Home meals"), ("experiences", "Local experiences")]),
    midstay_clean=None,  # a light daily tidy by the host, not a tracked job
    self_check_in=False,
)
PACKS["boutique_hotel"] = _stay_pack(
    "Boutique hotel / resort / guesthouse",
    "room",
    ("Room ready", "Check-in", "Staying", "Check-out", "Settle", "Done"),
    {"name": "Room ready", "items": _items(_ROOM_READY)},
    {"name": "Room check after check-out", "items": _items(_ROOM_INSPECT)},
    flow="room",
    flows=("room",),
    host_label="Front desk",
    duties=("front_desk", "housekeeping", "maintenance", "fnb", "ops_manager"),
    issue_types=_issues(
        [
            ("room_fault", "Room fault (AC, TV, plumbing)", "ac"),
            ("housekeeping", "Housekeeping request", "housekeeping"),
            ("food", "Food and room service", "food"),
        ]
    ),
    paperwork=("ID at the desk", "Form C for foreign guests"),
    addons=_addons([("upgrade", "Room upgrade"), ("dining", "Dining"), ("spa", "Spa"), ("transfer", "Airport transfer")]),
    midstay_clean=None,  # daily housekeeping belongs to the room board (Ops 2e)
    self_check_in=False,
)

FLOWS: dict[str, dict] = {
    "trip": {"label": "Trip", "machine": "trip", "room_board": False},
    "whole_unit": {"label": "Whole-unit stay", "machine": "stay", "room_board": False},
    # room: files and checklists run on the stay machine now; the daily room board is card "Ops 2e".
    "room": {"label": "Room stay", "machine": "stay", "room_board": False},
}

# A booking cancelled while its file is in one of these states turns the file to cancelled (before the guest/trip starts).
CANCELLABLE = tuple(dict.fromkeys(s for p in PACKS.values() for s in p["cancellable"]))
STAY_PACKS = tuple(k for k, p in PACKS.items() if FLOWS[p["flow"]]["machine"] == "stay")
TRIP_PACKS = tuple(k for k, p in PACKS.items() if FLOWS[p["flow"]]["machine"] == "trip")

# tenants.business_type -> pack. Sign-up and Settings offer BUSINESS_TYPES; older or other values still map.
_BY_BUSINESS_TYPE = {
    "caravan": "caravan_rv",
    "caravan_rv": "caravan_rv",
    "campervan": "caravan_rv",
    "villa": "villa",
    "villa_resort": "villa",
    "farmhouse": "villa",
    "vacation_rental": "vacation_rental",
    "apartment": "vacation_rental",
    "service_apartments": "vacation_rental",
    "homestay": "homestay",
    "hotel": "boutique_hotel",
    "boutique_hotel": "boutique_hotel",
    "resort": "boutique_hotel",
    "guesthouse": "boutique_hotel",
}
# A business type whose unit is not its pack's word (a farmhouse runs the villa pack).
_UNIT_WORD = {"farmhouse": "farmhouse"}

# What sign-up and Settings > Workspace offer, in order: value -> label (frontend lib/segments.ts mirrors it).
BUSINESS_TYPES = {
    "caravan": "Caravans and campervans",
    "villa_resort": "Villas",
    "farmhouse": "Farmhouses",
    "vacation_rental": "Vacation rentals and apartments",
    "homestay": "Homestays",
    "hotel": "Boutique hotels",
    "resort": "Resorts",
    "guesthouse": "Guesthouses",
}


def _norm(business_type: str | None) -> str:
    return (business_type or "").strip().lower()


def pack_for_business_type(business_type: str | None) -> str | None:
    """The pack a business runs, or None when its category has none (not set or unknown)."""
    return _BY_BUSINESS_TYPE.get(_norm(business_type))


def unit_word_for(business_type: str | None) -> str | None:
    pack = pack_for_business_type(business_type)
    if pack is None:
        return None
    return _UNIT_WORD.get(_norm(business_type), PACKS[pack]["unit_word"])


def get(pack: str) -> dict:
    if pack not in PACKS:
        raise KeyError(f"unknown ops pack {pack!r}")
    return PACKS[pack]


def flow_of(pack: str) -> str:
    return get(pack)["flow"]


def machine(pack: str) -> str:
    """Which state machine runs a pack's files: trip (ops_trip_service) or stay (ops_stay_service)."""
    return FLOWS[flow_of(pack)]["machine"]


def is_stay(pack: str | None) -> bool:
    return bool(pack) and pack in STAY_PACKS


def step_of(pack: str, state: str) -> int:
    return get(pack)["states"][state]

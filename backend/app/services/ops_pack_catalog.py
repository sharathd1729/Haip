"""Ops packs, defined in code (like lead_playbook_catalog). A pack names a business's units and files, its six steps, its
states and its default checklists. A business's category (tenants.business_type) picks its pack; the later sign-up form only
sets that category.

caravan_rv (phase 1, ops_trip_service) and villa (phase 4, ops_stay_service) are built. Other packs are added here when their
first client starts.
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


def _items(rows: list) -> list[dict]:
    return [
        {"key": k, "label": label, "critical": crit, "source": src, "photo": photo} for k, label, crit, src, photo in rows
    ]


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
        },
    },
    "villa": {
        "label": "Villa",
        "unit_word": "villa",
        "file_word": "stay",
        "step_names": ("Get ready", "Welcome", "Staying", "Check-out", "Settle", "Done"),
        "states": {
            "preparing": 0,
            "ready": 1,
            "staying": 2,
            "checked_out": 3,
            "settling": 4,
            "closed": 5,
            "cancelled": 5,
        },
        "first_state": "preparing",
        "cancellable": ("preparing", "ready"),
        "checklists": {
            "readiness": {"name": "Ready to welcome", "items": _items(_VILLA_READY)},
            "inspection": {"name": "Check-out inspection", "items": _items(_VILLA_INSPECT)},
        },
    },
}

# A booking cancelled while its file is in one of these states turns the file to cancelled (before the guest/trip starts).
CANCELLABLE = tuple(s for p in PACKS.values() for s in p["cancellable"])

# tenants.business_type today (sign-up) -> pack. The six future categories map one to one.
_BY_BUSINESS_TYPE = {
    "caravan": "caravan_rv",
    "caravan_rv": "caravan_rv",
    "villa": "villa",
    "villa_resort": "villa",
}


def pack_for_business_type(business_type: str | None) -> str | None:
    """The pack a business runs, or None when its category has no pack built yet."""
    return _BY_BUSINESS_TYPE.get((business_type or "").strip().lower())


def get(pack: str) -> dict:
    if pack not in PACKS:
        raise KeyError(f"unknown ops pack {pack!r}")
    return PACKS[pack]


def step_of(pack: str, state: str) -> int:
    return get(pack)["states"][state]

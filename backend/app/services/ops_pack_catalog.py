"""Ops packs, defined in code (like lead_playbook_catalog). A pack names a business's units and files, its six steps, its
states and its default checklists. A business's category (tenants.business_type) picks its pack; the later sign-up form only
sets that category.

Only caravan_rv is built (phase 1). Other packs are added here when their first client starts; nothing else in Ops changes.
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
}

# tenants.business_type today (sign-up) -> pack. The six future categories map one to one.
_BY_BUSINESS_TYPE = {"caravan": "caravan_rv", "caravan_rv": "caravan_rv"}


def pack_for_business_type(business_type: str | None) -> str | None:
    """The pack a business runs, or None when its category has no pack built yet."""
    return _BY_BUSINESS_TYPE.get((business_type or "").strip().lower())


def get(pack: str) -> dict:
    if pack not in PACKS:
        raise KeyError(f"unknown ops pack {pack!r}")
    return PACKS[pack]


def step_of(pack: str, state: str) -> int:
    return get(pack)["states"][state]

"""Villa staff photos on WhatsApp (phase 4): the caretaker, cook and cleaner send a photo with a word, like the caravan crew
(ops_photo_intake, which hands villa staff here and supplies the shared helpers: shrink, bills, flags).

  "pool", "bedroom", "garden", "ac", "gas", "towels" ...   a Ready to welcome check before arrival; after check-out the same
                                    word is the inspection, compared side by side with the arrival photo (ops_photo_compare)
  "chlorine" / "ph"                 the pool test kit: chlorine 1-3 ppm and pH 7.2-7.8, anything else is red + a flag
  "damage" / "missing"              inspection: what broke or went missing (red when the photo shows a problem)
  "clean" / "cleaned"               a mid-stay clean is done
  "groceries" / "bill" / ...        a bill, filed as an expense of the stay
Nothing is guessed: an unreadable or low-confidence photo changes nothing and the sender is asked to resend.
"""

import re
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.ops import StaffProfile
from app.models.ops_files import OpsFile, OpsJobItem
from app.services import ops_money as money
from app.services import ops_photo_compare as compare
from app.services import ops_photo_intake as intake
from app.services import ops_stay_service as stays
from app.services import ops_trip_service as trips

PROMPT_VERSION = "ops-villa-photo-v1"
CHLORINE_PPM = (Decimal(1), Decimal(3))
PH = (Decimal("7.2"), Decimal("7.8"))

PROMPTS = {
    "chlorine": (
        "This is a photo of a pool water test kit (colour comparator or test strip) or a digital tester. Read the free "
        'chlorine in ppm (mg/L) and the pH. Keys: "chlorine_ppm" (number), "ph" (number), "confidence". '
        + intake._COMMON
    ),
    "check": (
        'A villa caretaker is proving this item before guests arrive: "{label}". Look at the photo. Keys: "shows_item" '
        '(true if the photo really shows that item), "ok" (true if it looks clean, working and ready), "problems" (a list '
        'of short plain phrases, e.g. "leaves in the pool", "bed not made"), "confidence". ' + intake._COMMON
    ),
    "inspect": (
        'A villa caretaker is checking this after the guests left: "{label}". Keys: "shows_item" (true if the photo shows '
        'it), "ok" (true if nothing is damaged, dirty or missing), "problems" (short plain phrases), "confidence". '
        + intake._COMMON
    ),
}

ALIASES = {
    "pool": ("pool", "swimming"),
    "chlorine": ("chlorine", "ph", "test kit", "water test", "testkit"),
    "bedrooms": ("bedroom", "bedrooms", "bed", "beds", "room", "rooms"),
    "ac": ("ac", "a/c", "aircon", "hot water", "geyser", "heater"),
    "wifi": ("wifi", "wi-fi", "wi fi", "internet", "router"),
    "garden": ("garden", "lawn", "outdoor", "seating", "deck"),
    "kitchen": ("gas", "kitchen", "stove", "cylinder"),
    "welcome": ("welcome", "kit", "hamper"),
    "linen": ("towel", "towels", "linen", "sheets"),
    "damage": ("damage", "damaged", "broken", "breakage", "crack"),
    "missing": ("missing", "lost"),
}
_CLEAN = re.compile(r"\b(clean|cleaned|cleaning|housekeeping)\b", re.IGNORECASE)


def classify(caption: str | None, item_keys: list[str]) -> tuple[str | None, str | None]:
    """(kind, detail): ("bill", category) | ("clean", None) | ("check", item key) | (None, None). Bills win over checks."""
    c = (caption or "").strip()
    if not c:
        return None, None
    for cat, pat in intake._BILL.items():
        if re.search(pat, c, re.IGNORECASE):
            return "bill", cat
    w = intake._words(c)
    for key in (
        "chlorine",
        "damage",
        "missing",
        *ALIASES,
    ):  # specific words first: "pool test kit" is the chlorine check
        if key in item_keys and any(f" {n} " in w for n in ALIASES[key]):
            return "check", key
    if _CLEAN.search(c):
        return "clean", None
    return None, None


def read_chlorine(ans: dict) -> tuple[bool | None, list[str], str]:
    """(in range?, problems, text). None = unreadable (ask again)."""
    cl, ph = intake._num(ans.get("chlorine_ppm")), intake._num(ans.get("ph"))
    if intake._confidence(ans) < intake.MIN_CONFIDENCE or cl is None or ph is None:
        return None, [], ""
    problems = []
    if not CHLORINE_PPM[0] <= cl <= CHLORINE_PPM[1]:
        problems.append(f"chlorine {cl} ppm (should be 1-3)")
    if not PH[0] <= ph <= PH[1]:
        problems.append(f"pH {ph} (should be 7.2-7.8)")
    return not problems, problems, f"Chlorine {cl} ppm, pH {ph}"


def _files(db: Session, tenant_id: str, staff: StaffProfile) -> list[OpsFile]:
    return [
        f
        for f in db.query(OpsFile).filter(
            OpsFile.tenant_id == tenant_id, OpsFile.pack == stays.PACK, OpsFile.state.in_(stays.LIVE)
        )
        if staff.id in money.crew_ids(f)
    ]


def pick(db: Session, files: list[OpsFile], caption: str | None) -> tuple[OpsFile | None, str | None, str | None]:
    """The file the photo is about, and its (kind, detail). On a turnover day the caretaker has a stay that just left and
    the next one arriving: a check goes to whichever still has that item open, the inspection first."""
    order = sorted(
        files, key=lambda f: ({"checked_out": 0, "staying": 1}.get(f.state, 2), money.stay_of(db, f).check_in)
    )
    for f in order:
        kind_ = stays.job_kind(f)
        items = trips.readiness_items(db, f, kind_) if kind_ else []
        kind, detail = classify(caption, [i.key for i in items])
        if kind == "check" and next(i for i in items if i.key == detail).status == "pending":
            return f, kind, detail
    for f in order:  # nothing still open: the first file the caption makes sense for
        kind_ = stays.job_kind(f)
        kind, detail = classify(caption, [i.key for i in trips.readiness_items(db, f, kind_)] if kind_ else [])
        if kind == "clean" and f.state != "staying":
            continue
        if kind is not None:
            return f, kind, detail
    return (order[0] if order else None), None, None


def _verdict(item: OpsJobItem, key: str, ok: bool, problems: list[str], conf: float, extra: dict | None = None) -> None:
    item.photo_key = key
    item.ai_verdict = {"ok": ok, "problems": problems, "confidence": conf, "prompt": PROMPT_VERSION, **(extra or {})}


def _check(db, f, staff, jpeg, key, describe, fetch, item_key) -> intake.Outcome:
    kind_ = stays.job_kind(f)
    item = next(i for i in trips.readiness_items(db, f, kind_) if i.key == item_key)
    extra: dict = {}
    if item_key == "chlorine":
        ans, _ = describe(jpeg, PROMPTS["chlorine"])
        ok, problems, text = read_chlorine(ans)
        if ok is None:
            return intake.Outcome(
                "Could not read the test kit. Please send a clear photo of the colours with the word chlorine."
            )
        extra = {"reading": text}
        conf = intake._confidence(ans)
    else:
        arrival = next((i for i in trips.readiness_items(db, f) if i.key == item_key and i.photo_key), None)
        if kind_ == "inspection" and arrival is not None:
            ans, _ = describe(
                compare.side_by_side(fetch(arrival.photo_key), jpeg), compare.PROMPT.format(label=item.label)
            )
            extra = {"compared_with": arrival.photo_key}
        else:
            ans, _ = describe(jpeg, PROMPTS["inspect" if kind_ == "inspection" else "check"].format(label=item.label))
        conf = intake._confidence(ans)
        if ans.get("shows_item") is not True or conf < 0.6:
            return intake.Outcome(f'This photo does not clearly show "{item.label}". Please send it again.')
        problems = [str(p)[:120] for p in (ans.get("problems") or []) if str(p).strip()][:5]
        ok = ans.get("ok") is True and not problems
        text = ""
    _verdict(item, key, ok, problems, conf, extra)
    note = (
        (text or None)
        if ok
        else ("AI: " + "; ".join(problems or ["does not look right"]) + (f" ({text})" if text else ""))
    )
    stays.set_item(db, f, item.key, "green" if ok else "red", note, staff_id=staff.id)
    left = [i.label for i in trips.readiness_items(db, f, kind_) if i.photo_required and i.status == "pending"]
    tail = ("Still needed: " + ", ".join(left) + ".") if left else "All photos are in. Thank you."
    if ok:
        return intake.Outcome(f"Got it. {(text + '. ') if text else ''}{item.label} looks fine. {tail}")
    sends = intake._flag(
        db,
        f,
        f"{item.label}: {'; '.join(problems) or 'looks wrong'}",
        f"Photo from {staff.name}"
        + (" after check-out" if kind_ == "inspection" else "")
        + f": {'; '.join(problems)}.",
        "high" if item.critical or item_key == "chlorine" else "normal",
        "checklist",
    )
    return intake.Outcome(
        f"Thanks. It looks like: {'; '.join(problems) or 'something is wrong'}. The manager has been told. {tail}",
        sends,
    )


def handle(
    db: Session, tenant_id: str, staff: StaffProfile, *, raw: bytes, caption, message_id, describe, store, fetch=None
):
    files = _files(db, tenant_id, staff)
    f, kind, detail = pick(db, files, caption)
    if f is None:
        return intake.Outcome("No stay found for your number right now. Please check with the manager.")
    if kind is None:
        return intake.Outcome(
            "What is this photo? Send it again with one word: pool, chlorine, bedroom, ac, gas, garden, towels, clean, "
            "groceries or bill.",
            file_id=f.id,
        )
    if kind == "clean":
        job = stays.finish_cleaning(db, f, staff_id=staff.id)
        return intake.Outcome(
            "Thanks, the cleaning is marked done." if job else "No cleaning is due today. The manager has the photo.",
            file_id=f.id,
        )
    try:
        jpeg = intake.shrink(raw)
    except ValueError as exc:
        return intake.Outcome(
            f"Could not open that photo ({exc}). Please send it as a photo, not a file.", file_id=f.id
        )
    key = store(tenant_id, f.id, message_id, jpeg)
    if kind == "bill":
        ans, _ = describe(jpeg, intake.PROMPTS["bill"])
        out = intake._bill(db, f, staff, jpeg, key, ans, detail)
    else:
        out = _check(db, f, staff, jpeg, key, describe, fetch or _fetch, detail)
    out.file_id = f.id
    return out


def _fetch(key: str) -> bytes:
    from app.services import media_storage

    return media_storage.download_media(key)

"""Return vs handover photos (Ops phase 2). When a trip returns, ops_trip_service.end_trip opens a `return` job with the same
photo zones as the readiness checklist. The helper sends "return ac", "return water" ... ; each photo is put next to that
zone's handover photo in ONE side-by-side JPEG (Pillow) and the vision model says what changed. A difference = the zone goes
red and the manager gets "Possible damage: ..." suggesting a deposit deduction; the settle step "Vehicle checked on return"
shows the result (`summary`). Nothing is deducted automatically: the manager decides.
"""

import io
from collections.abc import Callable

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.models.ops import StaffProfile
from app.models.ops_files import OpsChecklistTemplate, OpsFile, OpsJob, OpsJobItem
from app.services import ops_money as money
from app.services import ops_photo_intake as intake
from app.services import ops_trip_service as trips

PROMPT_VERSION = "ops-return-v1"
PROMPT = (
    "Two photos of the same part of a rented caravan, side by side. LEFT = at handover, RIGHT = when it came back. Zone: "
    '"{label}". Keys: "same_zone" (true if both show the same part), "differences" (a list of short plain phrases for NEW '
    "damage, stains, missing or broken things on the RIGHT; ignore light, angle, people and normal tidiness), "
    '"damage_likely" (true if a difference could justify a deduction from the security deposit), "confidence". '
    + intake._COMMON
)
HEIGHT = 768


def compose(before: bytes, after: bytes) -> bytes:
    """Handover (left) and return (right) at the same height in one JPEG, each labelled."""
    imgs = []
    for raw in (before, after):
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            w = max(1, round(im.width * HEIGHT / im.height))
            imgs.append(im.resize((w, HEIGHT)))
    gap = 12
    out = Image.new("RGB", (imgs[0].width + gap + imgs[1].width, HEIGHT), "white")
    out.paste(imgs[0], (0, 0))
    out.paste(imgs[1], (imgs[0].width + gap, 0))
    draw = ImageDraw.Draw(out)
    for x, text in ((8, "HANDOVER"), (imgs[0].width + gap + 8, "RETURN")):
        draw.rectangle((x - 4, 4, x + 8 * len(text) + 4, 22), fill="black")
        draw.text((x, 8), text, fill="white")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _job(db: Session, f: OpsFile, kind: str) -> OpsJob | None:
    return (
        db.query(OpsJob).filter_by(tenant_id=f.tenant_id, file_id=f.id, kind=kind).order_by(OpsJob.created_at).first()
    )


def return_items(db: Session, f: OpsFile) -> list[OpsJobItem]:
    job = _job(db, f, "return")
    if job is None:
        return []
    items = db.query(OpsJobItem).filter_by(tenant_id=f.tenant_id, job_id=job.id).all()
    t = db.get(OpsChecklistTemplate, job.template_id) if job.template_id else None
    order = {it["key"]: n for n, it in enumerate(t.items or [])} if t is not None else {}
    return sorted(items, key=lambda i: (order.get(i.key, len(order)), i.key))


def summary(db: Session, f: OpsFile) -> dict:
    items = return_items(db, f)
    if not items:
        return {"words": "Compare with the handover photos", "items": [], "damage": []}
    done = [i for i in items if i.status != "pending"]
    damage = [i.label.split(",")[0].split(":")[0] for i in items if i.status == "red"]
    words = f"{len(done)} of {len(items)} return photos checked"
    words += f"; possible damage: {', '.join(damage)}" if damage else ("; no differences found" if done else "")
    return {
        "words": words,
        "damage": damage,
        "items": [
            {"key": i.key, "label": i.label, "status": i.status, "note": i.note, "has_photo": bool(i.photo_key)}
            for i in items
        ],
    }


def returned_file(db: Session, tenant_id: str, staff: StaffProfile) -> OpsFile | None:
    files = [
        f
        for f in db.query(OpsFile).filter(OpsFile.tenant_id == tenant_id, OpsFile.state == "returned")
        if staff.id in (money.details(f).driver_staff_id, money.details(f).helper_staff_id)
    ]
    return max(files, key=lambda f: f.returned_at) if files else None


def handle(
    db: Session,
    tenant_id: str,
    staff: StaffProfile,
    *,
    raw: bytes,
    caption: str,
    message_id: str,
    describe: intake.Describe | None = None,
    store: Callable[[str, str, str, bytes], str] | None = None,
    fetch: Callable[[str], bytes] | None = None,
) -> intake.Outcome:
    f = returned_file(db, tenant_id, staff)
    if f is None:
        return intake.Outcome("No returned trip found for your number. Please check with the manager.")
    items = return_items(db, f)
    rest = caption.strip()[len("return") :].strip()
    kind, key = intake.classify(rest, items)
    if kind != "check":
        return intake.Outcome(
            "Which part is this? Send it again with the word return and the part, for example: return ac.", file_id=f.id
        )
    try:
        jpeg = intake.shrink(raw)
    except ValueError as exc:
        return intake.Outcome(f"Could not open that photo ({exc}). Please send it as a photo.", file_id=f.id)
    item = next(i for i in items if i.key == key)
    item.photo_key = (store or intake._store)(tenant_id, f.id, message_id, jpeg)
    zone = item.label.split(",")[0].split(":")[0]
    before = next((i for i in trips.readiness_items(db, f) if i.key == key and i.photo_key), None)
    if before is None:
        trips._set(item, "pending", "No handover photo to compare: check by eye", None, staff.id)
        return intake.Outcome(
            f"Got the {zone} photo. There is no handover photo to compare, so the manager will check it.", file_id=f.id
        )
    if fetch is None:
        from app.services.media_storage import download_media as fetch
    pair = compose(fetch(before.photo_key), jpeg)
    ans, _prov = (describe or intake._default_describe)(pair, PROMPT.format(label=item.label))
    conf = intake._confidence(ans)
    if ans.get("same_zone") is not True or conf < 0.6:
        return intake.Outcome(
            f"This photo does not clearly show the same {zone} as at handover. Please send it again.", file_id=f.id
        )
    diffs = [str(d)[:120] for d in (ans.get("differences") or []) if str(d).strip()][:5]
    damage = bool(diffs) and ans.get("damage_likely") is True
    item.ai_verdict = {"ok": not diffs, "problems": diffs, "confidence": conf, "prompt": PROMPT_VERSION}
    trips._set(item, "red" if damage else "green", ("AI: " + "; ".join(diffs)) if diffs else None, None, staff.id)
    if not damage:
        money.event(
            db, f, f"Return photo {zone}: matches handover" + (f" ({'; '.join(diffs)})" if diffs else ""), auto=True
        )
        return intake.Outcome(f"Got it. {zone} matches the handover photo.", file_id=f.id)
    money.event(db, f, f"Return photo {zone}: possible damage ({'; '.join(diffs)})", auto=True)
    deposit = money.account(db, f)["deposit"]
    sends = intake._flag(
        db,
        f,
        f"possible damage: {zone}",
        f"Return photo from {staff.name} vs handover: {'; '.join(diffs)}. "
        + (
            f"Consider a deduction from the Rs {deposit['amount']:,} deposit."
            if deposit
            else "Consider charging for it."
        ),
        "high",
        "vehicle",
    )
    return intake.Outcome(f"Thanks. It looks like: {'; '.join(diffs)}. The manager has been told.", sends, f.id)

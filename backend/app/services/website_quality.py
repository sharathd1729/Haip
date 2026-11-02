"""Publish gate (website phase 3): a Lighthouse-style check of a v2 site from its spec and bound data, no browser.

Three scores out of 100 (share of checks passed) the owner sees in the publish checklist: speed, accessibility, search.
They WARN only. The one thing that BLOCKS publishing is a colour pair below WCAG AA contrast (schemas.site_spec rules,
the numbers a browser audit reports). A real Lighthouse run needs a headless browser; this is the static part of it:
what HAIP can know from the plan (photo sizes known so nothing jumps, image counts, alt text, headings, titles,
descriptions, structured data, contact details).
"""

from app.schemas.site_spec import contrast_problems

MAX_IMAGES_PER_PAGE = 24
MAX_SECTIONS_PER_PAGE = 12


def audit(doc: dict, bound: dict, assets: dict) -> dict:
    items: list[dict] = []

    def add(cat: str, key: str, ok: bool, title: str, detail: str, block: bool = False) -> None:
        items.append(
            {
                "category": cat,
                "key": key,
                "ok": ok,
                "title": title,
                "detail": detail,
                "level": "ok" if ok else ("block" if block else "warn"),
            }
        )

    pages = doc.get("pages", [])
    site = doc.get("site") or {}

    # speed
    no_size = [a for a, v in assets.items() if not (v.get("w") and v.get("h"))]
    add(
        "performance",
        "image_sizes",
        not no_size,
        "Photos keep their place while loading",
        f"{len(no_size)} photo(s) have no known size, so the page can jump as they load."
        if no_size
        else "Every photo has a known size: nothing jumps while the page loads.",
    )
    heavy = []
    for p in pages:
        n = 0
        for s in p["sections"]:
            data = bound.get(s["id"]) or {}
            media = data.get("media")
            n += len(media) if isinstance(media, list) else (1 if media else 0)
            n += sum(1 for i in data.get("items") or [] if isinstance(i, dict) and i.get("photo"))
        if n > MAX_IMAGES_PER_PAGE:
            heavy.append(p["title"])
    add(
        "performance",
        "image_count",
        not heavy,
        "Not too many photos on one page",
        "These pages load many photos: " + ", ".join(heavy)
        if heavy
        else f"Every page shows at most {MAX_IMAGES_PER_PAGE} photos.",
    )
    long_pages = [p["title"] for p in pages if len(p["sections"]) > MAX_SECTIONS_PER_PAGE]
    add(
        "performance",
        "sections",
        not long_pages,
        "Pages are a sensible length",
        "Split these long pages: " + ", ".join(long_pages) if long_pages else "Every page is a sensible length.",
    )
    add(
        "performance",
        "fonts",
        True,
        "Fonts load from your own site",
        "Two fonts, served with the site (no Google request).",
    )

    # accessibility
    pal = (doc.get("tokens") or {}).get("palette")
    problems = (
        contrast_problems(pal) if isinstance(pal, dict) and {"ink", "surface", "primary", "accent"} <= set(pal) else []
    )
    add(
        "accessibility",
        "contrast",
        not problems,
        "Text is readable on its background",
        "Colours too close: " + "; ".join(problems) if problems else "Every colour pair passes WCAG AA contrast.",
        block=True,
    )
    no_alt = [a for a, v in assets.items() if not (v.get("alt") or "").strip()]
    add(
        "accessibility",
        "alt_text",
        not no_alt,
        "Photos are described for screen readers",
        f"{len(no_alt)} photo(s) have no description. Add one in the photo library."
        if no_alt
        else "Every photo has a description.",
    )
    no_h1 = [
        p["title"]
        for p in pages
        if not any(
            (s.get("slots") or {}).get("headline") or (s.get("slots") or {}).get("heading") for s in p["sections"][:1]
        )
    ]
    add(
        "accessibility",
        "headings",
        not no_h1,
        "Each page opens with a heading",
        "Add a heading to the first section of: " + ", ".join(no_h1)
        if no_h1
        else "Every page starts with a clear heading.",
    )
    contact = site.get("contact") or {}
    add(
        "accessibility",
        "contact",
        bool(contact.get("phone") or contact.get("whatsapp")),
        "A way to call or message",
        "Guests who can't use a form can still reach you."
        if contact.get("phone") or contact.get("whatsapp")
        else "Add a phone or WhatsApp number.",
    )

    # search
    titles = [p["seo"]["title"] for p in pages]
    bad_t = [p["title"] for p in pages if not 10 <= len(p["seo"]["title"]) <= 70]
    add(
        "seo",
        "titles",
        not bad_t,
        "Search titles",
        "Give these pages a 10-70 character title: " + ", ".join(bad_t) if bad_t else "Every page has a search title.",
    )
    add(
        "seo",
        "unique_titles",
        len(set(titles)) == len(titles),
        "Each page has its own title",
        "Two pages share a title; search engines may show only one."
        if len(set(titles)) != len(titles)
        else "No two pages share a title.",
    )
    bad_d = [p["title"] for p in pages if not 50 <= len(p["seo"].get("description") or "") <= 160]
    add(
        "seo",
        "descriptions",
        not bad_d,
        "Search descriptions",
        "Write a 50-160 character description for: " + ", ".join(bad_d) if bad_d else "Every page has a description.",
    )
    add(
        "seo",
        "share_image",
        bool(assets),
        "A photo for link previews",
        "Links shared on WhatsApp and Google show your photo." if assets else "Add at least one photo.",
    )
    add(
        "seo",
        "address",
        bool(contact.get("address")),
        "Your address for Google",
        "Shown to Google as your business address."
        if contact.get("address")
        else "Add your address so Google can place you on the map.",
    )
    types = {s["type"] for p in pages for s in p["sections"]}
    add(
        "seo",
        "rich_results",
        bool({"faq", "reviews"} & types),
        "Questions or reviews for rich results",
        "FAQs and reviews are marked up for Google."
        if {"faq", "reviews"} & types
        else "Add an FAQ or reviews section.",
    )

    scores = {}
    for cat in ("performance", "accessibility", "seo"):
        mine = [i for i in items if i["category"] == cat]
        scores[cat] = round(100 * sum(1 for i in mine if i["ok"]) / len(mine)) if mine else 100
    return {"scores": scores, "items": items}

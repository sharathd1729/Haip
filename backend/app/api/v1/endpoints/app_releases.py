"""Android in-app update for HAIP Calls and Yaad (two flavors of android/).

  GET /app/android/version?flavor=calls|yaad    latest published version: {available, version_code, version_name, notes,
                                                sha256, url}; {available: false} when none is published
  GET /app/android/download/{flavor}            the APK itself

Public on purpose: the app asks before anyone signs in, and an APK is not a secret (every build is signed with HAIP's key,
so Android refuses an update signed by anyone else). Files live in settings.APP_DOWNLOADS_DIR (the VPS's ./downloads,
mounted at /app/downloads), written by scripts/publish_android_release.py: <flavor>.apk + <flavor>.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(prefix="/app/android", tags=["app"])

FLAVOR = "^(calls|yaad)$"  # a closed list, so the name can never point outside the folder


def _manifest(flavor: str) -> dict | None:
    folder = Path(settings.APP_DOWNLOADS_DIR)
    meta, apk = folder / f"{flavor}.json", folder / f"{flavor}.apk"
    if not (meta.is_file() and apk.is_file()):
        return None
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
        return {
            "version_code": int(m["version_code"]),
            "version_name": str(m.get("version_name") or m["version_code"]),
            "notes": str(m.get("notes") or ""),
            "sha256": str(m.get("sha256") or ""),
        }
    except (ValueError, KeyError, TypeError):
        return None


@router.get("/version")
def latest_version(flavor: str = Query(..., pattern=FLAVOR)):
    m = _manifest(flavor)
    if m is None:
        return {"available": False}
    return {"available": True, **m, "url": f"/api/v1/app/android/download/{flavor}"}


@router.get("/download/{flavor}")
def download(flavor: str = PathParam(..., pattern=FLAVOR)):
    m = _manifest(flavor)
    if m is None:
        raise HTTPException(status_code=404, detail="No version of this app has been published yet.")
    name = "HAIP-Calls" if flavor == "calls" else "Yaad"
    return FileResponse(
        Path(settings.APP_DOWNLOADS_DIR) / f"{flavor}.apk",
        media_type="application/vnd.android.package-archive",
        filename=f"{name}-{m['version_name']}.apk",
    )

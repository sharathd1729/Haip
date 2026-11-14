"""
Publish an Android build for the in-app update (HAIP Calls or Yaad). Run on the VPS, in /opt/haip, with plain python3
(no app imports, no database):

    python3 backend/scripts/publish_android_release.py --flavor yaad --apk ~/yaad-0.1.9-release.apk \
        --version-code 9 --notes "Ask Yaad and the daily summary email"

Copies the APK to ./downloads/<flavor>.apk and writes ./downloads/<flavor>.json; the api container serves both
(/api/v1/app/android/version and /download). Phones with an older version see "Update available" next time the app opens.

--version-code is the build's run number: the APK file name ends in 0.1.<run number>, so yaad-0.1.9-release.apk = 9.
Refuses a version code that is not higher than the one already published (Android would refuse the install anyway).
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--flavor", required=True, choices=["calls", "yaad"])
    ap.add_argument("--apk", required=True, type=Path)
    ap.add_argument("--version-code", required=True, type=int)
    ap.add_argument("--version-name", help="default 0.1.<version code>")
    ap.add_argument("--notes", default="", help="one line shown in the update prompt")
    ap.add_argument("--dir", type=Path, default=Path("downloads"), help="the folder mounted at /app/downloads")
    args = ap.parse_args()

    if not args.apk.is_file() or args.apk.read_bytes()[:2] != b"PK":
        print(f"{args.apk} is not an APK file.")
        return 1
    args.dir.mkdir(parents=True, exist_ok=True)
    meta = args.dir / f"{args.flavor}.json"
    if meta.is_file():
        current = json.loads(meta.read_text(encoding="utf-8")).get("version_code", 0)
        if args.version_code <= int(current):
            print(f"Version code {args.version_code} is not newer than the published {current}; nothing changed.")
            return 1
    data = args.apk.read_bytes()
    tmp = args.dir / f"{args.flavor}.apk.tmp"
    tmp.write_bytes(data)
    tmp.replace(args.dir / f"{args.flavor}.apk")  # swap in one step: a phone mid-download never gets half a file
    meta.write_text(json.dumps({
        "version_code": args.version_code,
        "version_name": args.version_name or f"0.1.{args.version_code}",
        "notes": args.notes,
        "sha256": hashlib.sha256(data).hexdigest(),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    print(f"Published {args.flavor} {args.version_name or f'0.1.{args.version_code}'} ({len(data) // 1024} KB).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

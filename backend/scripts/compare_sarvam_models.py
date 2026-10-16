"""Run ONE real call recording through Sarvam saaras:v3 and saaras:v4 and compare them, so the model can be switched on evidence.

It only reads: it fetches the recording, submits two batch jobs to Sarvam (a few minutes of API credit), and prints a comparison.
Nothing is saved in HAIP and the production setting is NOT changed. Transcript text is not printed unless you ask (--show-text).

What to look at in the output:
  * speakers: 2 is right (agent + guest). 1 means diarization failed (the old v2.5 problem).
  * turns / seconds: similar numbers on both = comparable segmentation; the job time shows the speed difference.
  * words and overlap: how much of the two transcripts agree; the language each detected.
  * --keyterms "Ratha,Coorg": v4 only, shows whether naming your brands/places helps.

Usage (inside the API container, against production; use a call that has a recording and was a real conversation):
    docker compose -f docker-compose.prod.yml exec -T api python3 scripts/compare_sarvam_models.py --call-id <call id>
    docker compose -f docker-compose.prod.yml exec -T api python3 scripts/compare_sarvam_models.py --file /tmp/call.mp3 --keyterms "Ratha,Coorg"
When v4 looks at least as good, switch with SARVAM_STT_MODEL=saaras:v4 in backend/.env and restart api and worker.
"""
import argparse
import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.adapters.transcription.sarvam import SarvamAdapter  # noqa: E402
from app.core.config import settings  # noqa: E402


def load_audio(call_id: str | None, path: str | None) -> bytes:
    if path:
        with open(path, "rb") as f:
            return f.read()
    from app.core.database import SessionLocal
    from app.models.call import Call

    db = SessionLocal()
    try:
        call = db.query(Call).filter_by(id=call_id).first()
        if call is None or not call.recording_s3_key:
            raise SystemExit("That call has no recording.")
        key = call.recording_s3_key
        if os.path.isabs(key) and os.path.exists(key):
            with open(key, "rb") as f:
                return f.read()
        from app.services.media_storage import _s3_client

        return _s3_client().get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)["Body"].read()
    finally:
        db.close()


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", (text or "").lower()))


def run_model(audio: bytes, model: str, keyterms: str) -> dict:
    settings.SARVAM_STT_MODEL = model
    settings.SARVAM_KEYTERMS = keyterms if model == "saaras:v4" else ""
    t0 = time.time()
    try:
        result = asyncio.run(SarvamAdapter().transcribe(audio, direction="inbound"))
    except Exception as exc:  # noqa: BLE001
        return {"model": model, "error": f"{type(exc).__name__}: {str(exc)[:200]}", "seconds": time.time() - t0}
    speakers = {t.speaker for t in result.turns}
    return {"model": model, "seconds": time.time() - t0, "turns": len(result.turns), "speakers": sorted(speakers),
            "words": len(words(result.raw_text)), "raw": result.raw_text, "language": result.language,
            "audio_seconds": result.turns[-1].t1 if result.turns else 0.0, "result": result}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--call-id")
    src.add_argument("--file")
    ap.add_argument("--keyterms", default="", help="comma-separated names/brands for v4")
    ap.add_argument("--show-text", action="store_true", help="also print the first lines of each transcript")
    args = ap.parse_args()
    if not settings.SARVAM_API_KEY:
        raise SystemExit("SARVAM_API_KEY is not set.")

    audio = load_audio(args.call_id, args.file)
    print(f"recording: {len(audio) / 1e6:.1f} MB; submitting to saaras:v3 then saaras:v4 (a few minutes)...\n")
    runs = [run_model(audio, m, args.keyterms) for m in ("saaras:v3", "saaras:v4")]
    for r in runs:
        if "error" in r:
            print(f"{r['model']:11} FAILED after {r['seconds']:.0f}s: {r['error']}")
            continue
        print(f"{r['model']:11} job {r['seconds']:.0f}s | audio {r['audio_seconds']:.0f}s | turns {r['turns']} | speakers {r['speakers']} | "
              f"words {r['words']} | language {r['language']}")
    ok = [r for r in runs if "error" not in r]
    if len(ok) == 2:
        a, b = words(ok[0]["raw"]), words(ok[1]["raw"])
        print(f"\nwords both transcripts share: {len(a & b) / max(1, len(a | b)):.0%}")
        two = {r["model"]: len(r["speakers"]) == 2 for r in ok}
        print("two speakers found (diarization worked): " + ", ".join(f"{m}={v}" for m, v in two.items()))
    if args.show_text:
        for r in ok:
            print(f"\n--- {r['model']} (first turns) ---")
            for t in r["result"].turns[:6]:
                print(f"[{t.speaker}] {t.text[:140]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

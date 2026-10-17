# Reading guide: Retained movie audit: stream archived USM data through diagnostics and
# collect decode evidence.
# Editing notes: This checks retained media without replacing the native movie player.
# Codec success alone does not prove in-game audio, orientation or Skip behavior.
# Checks: docs/04-verification.md.
# Project navigation: docs/README.md and docs/05-source-guide.md.
import concurrent.futures, datetime, hashlib, json, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "offline"))
FFMPEG = shutil.which("ffmpeg")
if not FFMPEG:
    raise SystemExit(
        "ffmpeg is required for this optional audit; no game files were changed."
    )
from asset_store import records, ArchivedAsset

movies = [(n, r) for n, r in records().items() if n.endswith(".usm")]


def check(pair):
    """Audit one retained movie stream and return its decoding evidence."""
    name, record = pair
    try:
        data = ArchivedAsset(record).read_bytes()
        digest = hashlib.md5(data).hexdigest()
        if digest != record["md5"]:
            raise ValueError("Archive MD5 differs")
        result = subprocess.run(
            [
                FFMPEG,
                "-nostdin",
                "-v",
                "error",
                "-threads",
                "1",
                "-i",
                "pipe:0",
                "-map",
                "0:v:0",
                "-an",
                "-f",
                "null",
                "-",
            ],
            input=data,
            capture_output=True,
            timeout=180,
        )
        return {
            "path": name,
            "bytes": len(data),
            "md5Verified": True,
            "decodeExit": result.returncode,
            "errors": result.stderr.decode(errors="replace")[:700],
        }
    except Exception as e:
        return {"path": name, "error": str(e)}


results = []
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for result in pool.map(check, movies):
        results.append(result)
        if len(results) % 20 == 0:
            print("Checked", len(results), "/", len(movies), flush=True)
report = {
    "scope": "Full video-stream decoding from original ZIP assets through ffmpeg pipes; no audio or in-game presentation certification",
    "results": results,
}
p = (
    ROOT
    / "state/verification"
    / datetime.datetime.now(datetime.timezone.utc).date().isoformat()
)
p.mkdir(parents=True, exist_ok=True)
(p / "movie-audit.json").write_text(json.dumps(report, indent=2) + "\n")
print(
    "Finished:",
    len(results),
    "clean:",
    sum(r.get("decodeExit") == 0 and not r.get("errors") for r in results),
    "problems:",
    sum(r.get("decodeExit") != 0 or bool(r.get("errors")) for r in results),
    flush=True,
)

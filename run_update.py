"""Stage a complete update before replacing any last-known-good model files.

The CLI only records status on failure and exits nonzero. Workflow publishing of
that status must not turn a failed update into a successful job.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import traceback
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent


def read_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def run_url():
    repo, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"https://github.com/{repo}/actions/runs/{run}" if repo and run else None


def read_status(data_dir):
    try:
        return read_json(data_dir / "run_status.json")
    except (ValueError, OSError):
        return {}


def record_failure(data_dir, error, diagnostics=None, started=None):
    previous = read_status(data_dir)
    status = {**previous, "schema_version": 1, "state": "failed", "using_cached_snapshot": True,
              "run_context": "github_actions" if run_url() else "local",
              "last_attempt_at_utc": started or now_iso(), "completed_at_utc": now_iso(),
              "run_url": run_url(), "error": error,
              "fx_fetch": diagnostics or {"sources": [], "note": "Fetch not completed"}}
    atomic_json(data_dir / "run_status.json", status)
    return 1


def run_update(engine=None, data_dir=None):
    data_dir = Path(data_dir or ROOT / "data")
    started = now_iso()
    try:
        if engine is None:
            import main as engine
        from validation_audit import build_audit
        previous = read_status(data_dir)
        before = read_json(data_dir / "fx_signals.json")
        with tempfile.TemporaryDirectory(prefix="fx-update-") as tmp:
            stage = Path(tmp) / "data"
            shutil.copytree(data_dir, stage)
            old_dir, old_cache = engine.DATA_DIR, engine.GDELT_CACHE_PATH
            try:
                engine.DATA_DIR = stage
                engine.GDELT_CACHE_PATH = stage / "gdelt_query_cache.json"
                engine.main()
                snapshot = read_json(stage / "fx_signals.json")
                if not snapshot.get("currencies"):
                    raise ValueError("No complete model snapshot was produced")
                # Also validate serialisation before publishing anything.
                for path in stage.glob("*.json"):
                    json.dumps(read_json(path), allow_nan=False)
                audit = build_audit(stage)
                atomic_json(stage / "validation_audit.json", audit)
                changed = snapshot.get("generated_at_utc") != before.get("generated_at_utc")
                status = {"schema_version": 1, "state": "updated" if changed else "no_new_market_data",
                          "run_context": "github_actions" if run_url() else "local",
                          "using_cached_snapshot": not changed, "last_attempt_at_utc": started,
                          "completed_at_utc": now_iso(), "last_successful_check_at_utc": now_iso(),
                          "last_model_update_at_utc": snapshot.get("generated_at_utc"),
                          "market_date": snapshot.get("latest_market_date"), "run_url": run_url(),
                          "fx_fetch": engine.FX_FETCH_DIAGNOSTICS,
                          "previous_failure": ({"at": previous.get("last_attempt_at_utc"),
                                               "error": previous.get("error"), "run_url": previous.get("run_url")}
                                              if previous.get("state") == "failed" else previous.get("previous_failure"))}
                atomic_json(stage / "run_status.json", status)
                # The repository/workflow publishes these files together in a
                # single commit. Never delete a history file during promotion.
                originals = {}
                try:
                    for path in stage.glob("*.json"):
                        target = data_dir / path.name
                        if not target.exists() or path.read_bytes() != target.read_bytes():
                            originals[target] = target.read_bytes() if target.exists() else None
                            replacement = target.with_suffix(".json.tmp")
                            shutil.copyfile(path, replacement)
                            replacement.replace(target)
                except Exception:
                    for target, original in originals.items():
                        if original is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.write_bytes(original)
                    raise
            finally:
                engine.DATA_DIR, engine.GDELT_CACHE_PATH = old_dir, old_cache
        return 0
    except Exception as exc:
        # Publish only a controlled error summary. Full traceback is unnecessary
        # for viewers; source-specific errors are captured without query strings.
        print(f"Update failed ({type(exc).__name__}); retaining previous model files")
        traceback.print_exc()
        return record_failure(data_dir, f"Update failed: {type(exc).__name__}. See workflow logs.",
                              getattr(engine, "FX_FETCH_DIAGNOSTICS", None), started)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-failure", help="Record a failed setup/build stage without dependencies")
    args = parser.parse_args()
    if args.record_failure:
        record_failure(ROOT / "data", args.record_failure)
    else:
        raise SystemExit(run_update())

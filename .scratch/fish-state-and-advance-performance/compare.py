"""Compare two formal benchmark receipts, allowing only code identity metadata."""
from __future__ import annotations
import argparse
import base64
import json
import zlib
from pathlib import Path

CORE = ("timeline.json", "events.json", "source_progression.json", "source_behavior.json")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def compare(first: Path, second: Path) -> dict:
    receipts = [read(p) for p in (first, second)]
    assert all(r["response"]["ok"] for r in receipts)
    if any("observation_trace" in r for r in receipts):
        assert all("observation_trace" in r for r in receipts), "both runs require traces"
        assert receipts[0]["observation_trace"] == receipts[1]["observation_trace"], "logical observations"
    outputs = [Path(r["response"]["result"]["output_dir"]) for r in receipts]
    assert read(Path(receipts[0]["final_observation"])) == read(Path(receipts[1]["final_observation"])), "final query DTO"
    for name in CORE:
        assert (outputs[0]/name).read_bytes() == (outputs[1]/name).read_bytes(), name
    checkpoints = [read(p/"final_checkpoint.json") for p in outputs]
    sessions = []
    for c in checkpoints:
        c.pop("model_digest")
        engine = c.pop("engine_state")
        assert engine["codec"] == "zlib-json-v1"
        s = json.loads(zlib.decompress(base64.b64decode(engine["data"])))
        s.pop("codeDigest")
        sessions.append(s)
    assert checkpoints[0] == checkpoints[1], "checkpoint behavior"
    assert sessions[0] == sessions[1], "source replay history"
    manifests = [read(p/"run_manifest.json") for p in outputs]
    for m in manifests:
        m.pop("model_digest")
        runtime = m["source_runtime"]
        for key in ("code_sha256", "integration_code_sha256", "timings_seconds",
                    "project_root", "data_root"):
            runtime.pop(key, None)
    assert manifests[0] == manifests[1], "manifest inputs or behavior"
    return {"core_bytes_identical": True, "checkpoint_history_identical": True,
            "final_observation_identical": True,
            "history_entries": len(sessions[0]["history"]),
            "observation_count": len(receipts[0].get("observation_trace", [])),
            "baseline_seconds": receipts[0]["timings"]["total"],
            "candidate_seconds": receipts[1]["timings"]["total"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.first, args.second), indent=2))

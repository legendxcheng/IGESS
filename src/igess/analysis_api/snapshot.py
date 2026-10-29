"""Bounded, identity-checked reads. Never load current model inputs."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import stat
from pathlib import Path
from typing import Any

from ..reporting.loader import ReportData
from ..run_registry import RunRecord
from .contracts import AnalysisError

MAX_BYTES = 256 * 1024 * 1024


def safe_path(root: Path, path: Path) -> Path:
    root, path = root.absolute(), path.absolute()
    if not path.is_relative_to(root):
        raise AnalysisError("unsafe_path", "Path escapes its registered root")
    # Reject reparse points including junctions, also on ancestors of the root.
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise AnalysisError("unsafe_path", "Linked analysis input is not allowed")
    return path


def read_bytes(root: Path, path: Path) -> bytes | None:
    return read_capture(root, path)[0]


def read_capture(root: Path, path: Path) -> tuple[bytes | None, tuple[int, ...] | None]:
    """Capture bytes and file identity together so equal-byte replacements are visible."""
    path = safe_path(root, path)
    try:
        before = path.stat()
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise AnalysisError("invalid_artifact", "Input is not a bounded regular file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not os.path.samestat(before, opened):
            raise AnalysisError("input_changed", "Input changed while opening")
        content = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    safe_path(root, path)
    current = path.stat()
    if (len(content) > MAX_BYTES or not os.path.samestat(opened, current)
            or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or (current.st_size, current.st_mtime_ns, current.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise AnalysisError("input_changed", "Input changed while reading")
    return content, (current.st_dev, current.st_ino, current.st_size,
                     current.st_mtime_ns, current.st_ctime_ns)


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def json_value(content: bytes, expected: type) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=pairs,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(value, expected):
        raise AnalysisError("invalid_artifact", f"Expected {expected.__name__}")
    return value


class RunSnapshot:
    def __init__(self, record: RunRecord):
        self.record = record
        self.files: dict[Path, bytes | None] = {}
        self.identities: dict[Path, tuple[int, ...] | None] = {}
        self.root = record.run_dir.absolute()
        status = self.read(record.status_path)
        if status is None:
            raise AnalysisError("input_changed", "Run status disappeared")
        status_data = json_value(status, dict)
        for key in ("status", "scenario_id", "engine_id", "model_digest"):
            if status_data.get(key) != getattr(record, key):
                raise AnalysisError("input_changed", "Run status changed", field=key)
        self.manifest = self.json("run_manifest.json", dict, required=False)
        for key in ("source_profiles", "execution_window", "source_runtime"):
            if key in self.manifest and not isinstance(self.manifest[key], dict):
                raise AnalysisError("invalid_artifact", "Invalid manifest object", field=key)
        for profile, scope in self.manifest.get("source_profiles", {}).items():
            if not isinstance(scope, dict):
                raise AnalysisError("invalid_artifact", "Invalid profile scope", profile=profile)
            for key in ("collection_growth", "pool_growth", "first_times"):
                if key in scope and not isinstance(scope[key], dict):
                    raise AnalysisError("invalid_artifact", "Invalid profile metadata", profile=profile, field=key)
            collection = scope.get("collection_growth", {})
            for key in ("initial_unlocked_entries", "initial_gun_facts"):
                if key in collection and not isinstance(collection[key], list):
                    raise AnalysisError("invalid_artifact", "Invalid collection baseline", field=key)
            if any(not isinstance(entry, dict) for entry in collection.get("initial_unlocked_entries", [])):
                raise AnalysisError("invalid_artifact", "Invalid collection entry")
            names = collection.get("display_names", {})
            if not isinstance(names, dict) or any(not isinstance(v, dict) for v in names.values()):
                raise AnalysisError("invalid_artifact", "Invalid frozen display names")
            if any(not isinstance(value, dict) for value in scope.get("first_times", {}).values()):
                raise AnalysisError("invalid_artifact", "Invalid lifecycle first time")
            lifecycle = scope.get("lifecycle_gun_milestones", [])
            if not isinstance(lifecycle, (list, dict)):
                raise AnalysisError("invalid_artifact", "Invalid lifecycle milestone collection")
            records = lifecycle.values() if isinstance(lifecycle, dict) else lifecycle
            if any(not isinstance(value, dict) for value in records):
                raise AnalysisError("invalid_artifact", "Invalid lifecycle milestone")
        profiles = self.manifest.get("profiles", [])
        if not isinstance(profiles, list) or any(not isinstance(p, str) for p in profiles) or len(set(profiles)) != len(profiles):
            raise AnalysisError("invalid_artifact", "Invalid manifest profiles")
        for key in ("scenario_id", "engine_id", "model_digest"):
            recorded, declared = getattr(record, key), self.manifest.get(key)
            if recorded is not None and declared is not None and recorded != declared:
                raise AnalysisError("identity_conflict", "Run and manifest disagree", field=key)
        names = self.manifest.get("artifacts", [])
        if not isinstance(names, list):
            raise AnalysisError("invalid_artifact", "Manifest artifacts must be a list")
        for name in names:
            self.artifact_path(name)

    def artifact_path(self, name: str) -> Path:
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or Path(name).is_absolute() or ".." in Path(name).parts):
            raise AnalysisError("unsafe_path", "Invalid artifact name")
        return safe_path(self.root, self.record.output_dir / name)

    def read(self, path: Path) -> bytes | None:
        path = path.absolute()
        if path not in self.files:
            self.files[path], self.identities[path] = read_capture(self.root, path)
        return self.files[path]

    def json(self, name: str, expected: type, *, required=True) -> Any:
        value = self.read(self.artifact_path(name))
        if value is None:
            if required:
                raise AnalysisError("artifact_missing", "Required artifact not recorded", artifact=name)
            return expected()
        return json_value(value, expected)

    def verify(self) -> None:
        for path, content in self.files.items():
            if read_capture(self.root, path) != (content, self.identities[path]):
                raise AnalysisError("input_changed", "Analysis inputs changed during evaluation")

    def provenance(self) -> dict[str, Any]:
        return {"run_id": self.record.run_id, "manifest": self.manifest,
                "input_digests": {p.relative_to(self.root).as_posix(): digest(b)
                                  for p, b in self.files.items() if b is not None}}

    def report_data(self) -> ReportData:
        if self.record.status != "success":
            raise AnalysisError("run_not_successful", "Analysis requires a successful registered run")
        if not self.manifest:
            raise AnalysisError("identity_incomplete", "Analysis requires a run manifest")
        timeline = self.json("timeline.json", list)
        events = self.json("events.json", list)
        analysis = self.json("analysis.json", dict)
        for rows in (timeline, events):
            for row in rows:
                if not isinstance(row, dict) or type(row.get("time_seconds")) is not int:
                    raise AnalysisError("invalid_artifact", "Invalid timed row")
                if not isinstance(row.get("profile_id"), str) or not row["profile_id"]:
                    raise AnalysisError("invalid_artifact", "Invalid row profile")
                for key in ("details", "resources", "generators_owned"):
                    if key in row and not isinstance(row[key], dict):
                        raise AnalysisError("invalid_artifact", "Invalid row object", field=key)
                if row.get("scenario_id", self.record.scenario_id) != self.record.scenario_id:
                    raise AnalysisError("identity_conflict", "Artifact scenario differs")
                profiles = self.manifest.get("profiles", [])
                if profiles and row.get("profile_id") not in profiles:
                    raise AnalysisError("identity_conflict", "Artifact profile differs")
        for event in events:
            if not isinstance(event.get("kind"), str) or not event["kind"] or not isinstance(event.get("item_id", ""), str):
                raise AnalysisError("invalid_artifact", "Event kind/item_id must be text")
        execution = self.manifest.get("execution_window", {})
        for profile in self.manifest.get("profiles", []):
            times = [r["time_seconds"] for r in timeline if r["profile_id"] == profile]
            if not times:
                raise AnalysisError("artifact_missing", "Profile timeline not recorded")
            start, end = min(times), max(times)
            if (execution.get("start_seconds", start) != start or execution.get("end_seconds", end) != end):
                raise AnalysisError("identity_conflict", "Execution window and timeline disagree")
            if any(not start <= e["time_seconds"] <= end for e in events if e["profile_id"] == profile):
                raise AnalysisError("identity_conflict", "Event outside observed execution window")
        payback = self.read(self.artifact_path("payback.csv"))
        progression = self.json("source_progression.json", dict, required=False)
        source_profiles = progression.get("profiles", {})
        if not isinstance(source_profiles, dict) or any(not isinstance(rows, list) or
                any(not isinstance(row, dict) for row in rows) for rows in source_profiles.values()):
            raise AnalysisError("invalid_artifact", "Invalid source progression profiles")
        return ReportData(self.record.output_dir, self.manifest, timeline, events, analysis,
            list(csv.DictReader(io.StringIO(payback.decode("utf-8-sig")))) if payback else [],
            [p.name for p, b in self.files.items() if b is None],
            source_progression=progression,
            source_behavior=self.json("source_behavior.json", dict, required=False))

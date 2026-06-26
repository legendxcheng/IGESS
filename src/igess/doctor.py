from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .linter import ConfigLinter
from .loader import ConfigLoader


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    checks: list[dict[str, str]]
    summary: str


def run_doctor(project: str | Path, config: str | Path, tables: str | Path) -> DoctorReport:
    project = Path(project)
    config_path = _resolve(project, config)
    tables_path = _resolve(project, tables)
    checks: list[dict[str, str]] = []
    checks.append(_check("config_exists", config_path.exists(), str(config_path)))
    checks.append(_check("tables_exist", tables_path.exists(), str(tables_path)))
    if config_path.exists() and tables_path.exists():
        try:
            raw = ConfigLoader.load(config_path, tables_path)
            ConfigLinter.validate(raw)
            checks.append(_check("lint", True, "Config OK"))
        except Exception as exc:  # noqa: BLE001 - diagnostics should capture all setup failures.
            checks.append(_check("lint", False, str(exc)))
    ok = all(check["status"] == "ok" for check in checks)
    summary = "; ".join(check["message"] for check in checks)
    return DoctorReport(ok=ok, checks=checks, summary=summary)


def format_doctor_report(report: DoctorReport) -> str:
    lines = ["IGESS Doctor", ""]
    for check in report.checks:
        lines.append(f"- {check['name']}: {check['status']} - {check['message']}")
    lines.extend(["", report.summary, ""])
    return "\n".join(lines)


def _resolve(project: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project / path


def _check(name: str, ok: bool, message: str) -> dict[str, str]:
    return {"name": name, "status": "ok" if ok else "failed", "message": message}

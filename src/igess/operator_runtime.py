"""Runtime boundary for the source-isolated execution-planner toolkit."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from typing import Any, Mapping, Sequence
import zipfile

import yaml

from .compare import compare_runs
from .builder import ModelBuilder
from .engines import EngineRegistry
from .gates import evaluate_gates
from .linter import ConfigLinter
from .loader import ConfigLoader
from .outputs import OutputWriter
from .reporting.static import generate_static_report
from .run_registry import RunRecord, RunRegistry


_BUNDLE_MANIFEST = "operator-manifest.json"
_RUN_METADATA = "operator_run.json"
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_INPUT_FILE_BYTES = 128 * 1024 * 1024
_MAX_INPUT_TOTAL_BYTES = 1024 * 1024 * 1024
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\r\n<>|\"]+")


class OperatorError(ValueError):
    """A safe, user-facing execution-toolkit error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class OperatorBundle:
    root: Path
    tool_version: str
    model_id: str
    engine_id: str
    config_path: Path
    schema_path: Path | None
    scenarios: tuple[str, ...]

    @classmethod
    def load(cls, root: str | os.PathLike[str]) -> "OperatorBundle":
        bundle_root = Path(root).expanduser().resolve(strict=True)
        manifest_path = bundle_root / _BUNDLE_MANIFEST
        try:
            if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                raise OperatorError("bundle_manifest_large", "工具包清单过大，无法启动。")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OperatorError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise OperatorError(
                "bundle_manifest_invalid",
                f"工具包清单无法读取：{type(error).__name__}",
            ) from None
        if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
            raise OperatorError("bundle_manifest_invalid", "工具包清单版本无效。")
        tool_version = _required_text(payload, "tool_version", "工具版本")
        model_id = _required_text(payload, "model_id", "模型标识")
        engine_id = _required_text(payload, "engine_id", "引擎标识")
        config_path = _bundle_file(bundle_root, payload.get("config"), {".yaml", ".yml"})
        schema_value = payload.get("schema")
        schema_path = (
            None
            if schema_value is None
            else _bundle_file(bundle_root, schema_value, {".pyc"})
        )
        scenarios_value = payload.get("scenarios")
        if (
            not isinstance(scenarios_value, Sequence)
            or isinstance(scenarios_value, (str, bytes, bytearray))
            or not scenarios_value
            or any(not isinstance(item, str) or not item for item in scenarios_value)
        ):
            raise OperatorError("bundle_manifest_invalid", "工具包未声明可用场景。")
        return cls(
            root=bundle_root,
            tool_version=tool_version,
            model_id=model_id,
            engine_id=engine_id,
            config_path=config_path,
            schema_path=schema_path,
            scenarios=tuple(dict.fromkeys(scenarios_value)),
        )


@dataclass(frozen=True, slots=True)
class InputFile:
    name: str
    sha256: str
    size_bytes: int

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class OperatorRunResult:
    record: RunRecord
    comparison_index: Path | None = None
    gates_ok: bool | None = None
    diagnostic_code: str | None = None


class OperatorService:
    """Run fixed scenarios against read-only exported JSON snapshots."""

    def __init__(
        self,
        bundle: OperatorBundle,
        history_root: str | os.PathLike[str] | None = None,
    ) -> None:
        self.bundle = bundle
        self.history_root = Path(history_root or default_history_root(bundle.model_id))
        self.registry = RunRegistry(self.history_root)
        self._engine_registry = EngineRegistry.standard()

    def scenarios(self) -> tuple[str, ...]:
        try:
            configured = ConfigLoader.load_rules_only(self.bundle.config_path).rules.scenarios
        except Exception as error:  # noqa: BLE001 - converted to safe startup error.
            raise OperatorError(
                "bundle_config_invalid",
                f"工具包场景配置无法读取：{type(error).__name__}",
            ) from None
        return tuple(item for item in self.bundle.scenarios if item in configured)

    def list_runs(self) -> list[RunRecord]:
        return self.registry.list_runs()

    def run(
        self,
        tables_directory: str | os.PathLike[str],
        scenario_id: str,
        *,
        baseline_run_id: str | None = None,
        include_diagnostic_input: bool = False,
    ) -> OperatorRunResult:
        if scenario_id not in self.scenarios():
            raise OperatorError("unknown_scenario", "所选场景不属于当前工具包。")
        source = _resolve_input_directory(tables_directory)
        with tempfile.TemporaryDirectory(prefix="igess-operator-snapshot-") as temporary:
            workspace = Path(temporary)
            snapshot = workspace / "json"
            input_files = snapshot_json_directory(source, snapshot)
            runtime_config = workspace / "economy.yaml"
            _write_runtime_config(self.bundle, snapshot, runtime_config)
            record = self._run_snapshot(
                runtime_config,
                snapshot,
                scenario_id,
                input_files,
            )
            record, diagnostic_code = self._sanitize_record(record, source, workspace)
            metadata = {
                "schema_version": 1,
                "tool_version": self.bundle.tool_version,
                "model_id": self.bundle.model_id,
                "engine_id": self.bundle.engine_id,
                "scenario_id": scenario_id,
                "input_directory_name": source.name,
                "input_files": [item.payload() for item in input_files],
                "diagnostic_code": diagnostic_code,
                "comparison": None,
                "gates": None,
            }
            if include_diagnostic_input:
                diagnostic_input = record.run_dir / "diagnostic-input"
                shutil.copytree(snapshot, diagnostic_input)
                metadata["diagnostic_input_included"] = True
            else:
                metadata["diagnostic_input_included"] = False
            _write_json(record.run_dir / _RUN_METADATA, metadata)

            comparison_index = None
            gates_ok = None
            if record.status == "success" and baseline_run_id:
                comparison_index, gates_ok = self._compare_and_gate(
                    record,
                    baseline_run_id,
                    metadata,
                )
            return OperatorRunResult(
                record=record,
                comparison_index=comparison_index,
                gates_ok=gates_ok,
                diagnostic_code=diagnostic_code,
            )

    def compatible_baselines(self, scenario_id: str) -> list[RunRecord]:
        result: list[RunRecord] = []
        for record in self.list_runs():
            metadata = self.run_metadata(record.run_id)
            if (
                record.status == "success"
                and record.scenario_id == scenario_id
                and metadata is not None
                and metadata.get("tool_version") == self.bundle.tool_version
            ):
                result.append(record)
        return result

    def run_metadata(self, run_id: str) -> dict[str, Any] | None:
        record = self._record(run_id)
        path = record.run_dir / _RUN_METADATA
        try:
            if path.stat().st_size > _MAX_MANIFEST_BYTES:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return dict(payload) if isinstance(payload, Mapping) else None

    def history_size_bytes(self) -> int:
        total = 0
        try:
            for root, _directories, files in os.walk(self.history_root, followlinks=False):
                for name in files:
                    try:
                        total += (Path(root) / name).stat().st_size
                    except OSError:
                        continue
        except OSError:
            return total
        return total

    def delete_run(self, run_id: str) -> None:
        record = self._record(run_id)
        root = self.history_root.resolve(strict=True)
        target = record.run_dir.resolve(strict=True)
        if target.parent != root or target.name != run_id or target.is_symlink():
            raise OperatorError("history_delete_unsafe", "运行记录路径不安全，拒绝删除。")
        shutil.rmtree(target)

    def clear_history(self) -> int:
        run_ids = [record.run_id for record in self.list_runs()]
        deleted = 0
        for run_id in run_ids:
            self.delete_run(run_id)
            deleted += 1
        return deleted

    def diagnostic_zip(self, run_id: str) -> bytes:
        record = self._record(run_id)
        metadata = self.run_metadata(run_id)
        if metadata is None:
            raise OperatorError("diagnostic_unavailable", "该运行没有可用诊断信息。")
        safe_status = {
            "run_id": record.run_id,
            "status": record.status,
            "scenario_id": record.scenario_id,
            "message": record.message,
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostic.json",
                json.dumps(
                    {"run": safe_status, "operator": metadata},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            if metadata.get("diagnostic_input_included") is True:
                input_root = record.run_dir / "diagnostic-input"
                if input_root.is_dir():
                    for path in sorted(input_root.glob("*.json"), key=lambda item: item.name):
                        if path.is_file() and not path.is_symlink():
                            archive.write(path, f"input/{path.name}")
        return stream.getvalue()

    def _compare_and_gate(
        self,
        candidate: RunRecord,
        baseline_run_id: str,
        metadata: dict[str, Any],
    ) -> tuple[Path, bool | None]:
        baseline = self._record(baseline_run_id)
        baseline_metadata = self.run_metadata(baseline_run_id)
        if baseline.status != "success":
            raise OperatorError("baseline_failed", "比较基线不是成功运行。")
        if baseline.scenario_id != candidate.scenario_id:
            raise OperatorError("baseline_scenario_mismatch", "比较基线与本次场景不同。")
        if (
            baseline_metadata is None
            or baseline_metadata.get("tool_version") != self.bundle.tool_version
        ):
            raise OperatorError("baseline_version_mismatch", "禁止跨工具版本比较。")
        comparison_root = candidate.run_dir / "comparison" / baseline.run_id
        comparison_index = compare_runs(
            baseline.output_dir,
            candidate.output_dir,
            comparison_root,
        )
        metadata["comparison"] = {
            "baseline_run_id": baseline.run_id,
            "index": comparison_index.relative_to(candidate.run_dir).as_posix(),
        }
        if _has_regression_gates(self.bundle.config_path, candidate.scenario_id):
            gates_root = candidate.run_dir / "gates" / baseline.run_id
            gates = evaluate_gates(
                baseline.output_dir,
                candidate.output_dir,
                self.bundle.config_path,
                gates_root,
            )
            gates_ok: bool | None = gates.ok
            metadata["gates"] = {
                "baseline_run_id": baseline.run_id,
                "configured": True,
                "ok": gates.ok,
                "results": (gates.output_dir / "gate_results.json")
                .relative_to(candidate.run_dir)
                .as_posix(),
            }
        else:
            gates_ok = None
            metadata["gates"] = {
                "baseline_run_id": baseline.run_id,
                "configured": False,
                "ok": None,
                "results": None,
            }
        _write_json(candidate.run_dir / _RUN_METADATA, metadata)
        return comparison_index, gates_ok

    def _run_snapshot(
        self,
        config_path: Path,
        tables_path: Path,
        scenario_id: str,
        input_files: Sequence[InputFile],
    ) -> RunRecord:
        run_dir = self.registry.new_run_dir(scenario_id)
        output_dir = run_dir / "output"
        report_dir = run_dir / "report"
        report_index = report_dir / "index.html"
        self.registry.write_status(
            run_dir,
            status="running",
            scenario_id=scenario_id,
            message="正在运行模拟",
            output_dir=output_dir,
            report_dir=report_dir,
            report_index=report_index,
        )
        prepared = None
        try:
            raw = ConfigLoader.load(config_path, tables_path)
            ConfigLinter.validate(raw)
            model = ModelBuilder.build(raw)
            adapter = self._engine_registry.resolve(model.config.engine_id)
            prepared = adapter.prepare(
                model,
                source_digest=_operator_source_digest(self.bundle.config_path, input_files),
                base_dir=config_path.parent,
            )
            execution = adapter.run_scenario(prepared, scenario_id)
            checkpoint_name = "final_checkpoint.json"
            checkpoint_path = adapter.write_checkpoint(
                execution,
                output_dir / checkpoint_name,
                model_digest=prepared.model_digest,
            )
            fish_run = prepared.engine_id != "generic"
            OutputWriter.write_all(
                execution.result,
                output_dir,
                model,
                model_digest=prepared.model_digest if fish_run else None,
                manifest_metadata=prepared.manifest_metadata,
                extra_artifacts=(checkpoint_name,) if checkpoint_path else (),
                domain_model=prepared.domain_model,
            )
            generate_static_report(output_dir, report_dir)
            return self.registry.write_status(
                run_dir,
                status="success",
                scenario_id=scenario_id,
                message="运行完成",
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
                kind="formal" if fish_run else None,
                model_digest=prepared.model_digest if fish_run else None,
                engine_id=prepared.engine_id if fish_run else None,
            )
        except Exception as error:  # noqa: BLE001 - persisted, then sanitized at the boundary.
            fish_run = prepared is not None and prepared.engine_id != "generic"
            return self.registry.write_status(
                run_dir,
                status="failed",
                scenario_id=scenario_id,
                message=str(error),
                output_dir=output_dir,
                report_dir=report_dir,
                report_index=report_index,
                kind="formal" if fish_run else None,
                model_digest=prepared.model_digest if fish_run else None,
                engine_id=prepared.engine_id if fish_run else None,
            )

    def _sanitize_record(
        self,
        record: RunRecord,
        input_root: Path,
        workspace: Path,
    ) -> tuple[RunRecord, str | None]:
        if record.status != "failed":
            return record, None
        message = sanitize_diagnostic(
            record.message,
            roots=(self.bundle.root, self.history_root, input_root, workspace),
        )
        code = "OPR-" + hashlib.sha256(message.encode("utf-8")).hexdigest()[:10].upper()
        safe_message = f"{message}（错误编号：{code}）"
        record = self.registry.write_status(
            record.run_dir,
            status="failed",
            scenario_id=record.scenario_id,
            message=safe_message,
            output_dir=record.output_dir,
            report_dir=record.report_dir,
            report_index=record.report_index,
            kind=record.kind if record.version is not None else None,
            change_id=record.change_id,
            model_digest=record.model_digest,
            engine_id=record.engine_id,
        )
        return record, code

    def _record(self, run_id: str) -> RunRecord:
        if not isinstance(run_id, str) or not run_id:
            raise OperatorError("run_not_found", "运行记录不存在。")
        record = next((item for item in self.list_runs() if item.run_id == run_id), None)
        if record is None:
            raise OperatorError("run_not_found", "运行记录不存在。")
        return record


def default_history_root(model_id: str) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "IGESS Operator" / _safe_component(model_id) / "runs"


def snapshot_json_directory(source: Path, destination: Path) -> tuple[InputFile, ...]:
    destination.mkdir(parents=True, exist_ok=False)
    files = sorted(source.glob("*.json"), key=lambda item: item.name.casefold())
    if not files:
        raise OperatorError("input_empty", "所选目录中没有 JSON 文件。")
    result: list[InputFile] = []
    total = 0
    for path in files:
        try:
            before = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(before.st_mode):
                raise OperatorError("input_file_unsafe", f"输入文件不是普通文件：{path.name}")
            if before.st_size > _MAX_INPUT_FILE_BYTES:
                raise OperatorError("input_file_large", f"输入文件过大：{path.name}")
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                encoded = handle.read(_MAX_INPUT_FILE_BYTES + 1)
                after = os.fstat(handle.fileno())
            current = path.stat()
        except OperatorError:
            raise
        except OSError as error:
            raise OperatorError(
                "input_read_failed",
                f"无法读取输入文件 {path.name}：{type(error).__name__}",
            ) from None
        if len(encoded) > _MAX_INPUT_FILE_BYTES:
            raise OperatorError("input_file_large", f"输入文件过大：{path.name}")
        if not (
            os.path.samestat(before, opened)
            and os.path.samestat(opened, after)
            and os.path.samestat(after, current)
            and before.st_size == len(encoded)
            and before.st_mtime_ns == current.st_mtime_ns
        ):
            raise OperatorError("input_changed", f"导表期间文件发生变化：{path.name}")
        total += len(encoded)
        if total > _MAX_INPUT_TOTAL_BYTES:
            raise OperatorError("input_total_large", "导表快照总大小超过限制。")
        (destination / path.name).write_bytes(encoded)
        result.append(
            InputFile(
                name=path.name,
                sha256="sha256:" + hashlib.sha256(encoded).hexdigest(),
                size_bytes=len(encoded),
            )
        )
    return tuple(result)


def sanitize_diagnostic(message: object, *, roots: Sequence[Path] = ()) -> str:
    text = str(message or "工具运行失败。")
    for root in roots:
        for value in {str(root), str(Path(root).absolute())}:
            if value:
                text = text.replace(value, "<本地路径>")
                text = text.replace(value.replace("\\", "/"), "<本地路径>")
    text = _WINDOWS_ABSOLUTE_PATH.sub("<本地路径>", text)
    text = " ".join(text.split())
    return text[:1000] or "工具运行失败。"


def _operator_source_digest(config_path: Path, files: Sequence[InputFile]) -> str:
    digest = hashlib.sha256()
    digest.update(b"IGESS_OPERATOR_INPUT_V1\0")
    digest.update(config_path.read_bytes())
    digest.update(b"\0")
    for item in files:
        digest.update(item.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _has_regression_gates(config_path: Path, scenario_id: str) -> bool:
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    gates = payload.get("regression_gates") if isinstance(payload, Mapping) else None
    scenario = gates.get(scenario_id) if isinstance(gates, Mapping) else None
    return isinstance(scenario, Mapping) and bool(scenario)


def _write_runtime_config(
    bundle: OperatorBundle,
    snapshot: Path,
    destination: Path,
) -> None:
    try:
        payload = yaml.safe_load(bundle.config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise OperatorError(
            "bundle_config_invalid",
            f"工具包配置无法读取：{type(error).__name__}",
        ) from None
    if not isinstance(payload, dict):
        raise OperatorError("bundle_config_invalid", "工具包配置根节点必须是对象。")
    engine = payload.setdefault("engine", {})
    if not isinstance(engine, dict):
        raise OperatorError("bundle_config_invalid", "工具包引擎配置无效。")
    if bundle.engine_id == "fish":
        engine["data_root"] = str(snapshot)
        if bundle.schema_path is None:
            raise OperatorError("bundle_schema_missing", "Fish 工具包缺少数据加载器。")
        engine["python_schema"] = str(bundle.schema_path)
    destination.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def _resolve_input_directory(value: str | os.PathLike[str]) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise OperatorError("input_missing", "请选择导表 JSON 所在目录。")
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise OperatorError(
            "input_unavailable",
            f"导表目录不可用：{type(error).__name__}",
        ) from None
    if not path.is_dir():
        raise OperatorError("input_not_directory", "所选导表路径不是目录。")
    return path


def _bundle_file(root: Path, value: object, suffixes: set[str]) -> Path:
    if not isinstance(value, str) or not value:
        raise OperatorError("bundle_manifest_invalid", "工具包清单缺少文件路径。")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise OperatorError("bundle_manifest_invalid", "工具包文件路径不安全。")
    try:
        path = (root / relative).resolve(strict=True)
        path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise OperatorError("bundle_manifest_invalid", "工具包文件不存在。") from None
    if not path.is_file() or path.suffix.lower() not in suffixes:
        raise OperatorError("bundle_manifest_invalid", "工具包文件类型无效。")
    return path


def _required_text(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise OperatorError("bundle_manifest_invalid", f"工具包清单缺少{label}。")
    return value


def _safe_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return normalized or "default"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


__all__ = [
    "InputFile",
    "OperatorBundle",
    "OperatorError",
    "OperatorRunResult",
    "OperatorService",
    "default_history_root",
    "sanitize_diagnostic",
    "snapshot_json_directory",
]

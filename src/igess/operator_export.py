"""Build and safely synchronize a sourceless execution-planner toolkit."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

import yaml


_DELIVERY_MANIFEST = ".igess-delivery-manifest.json"
_OPERATOR_MANIFEST = "operator-manifest.json"
_ALLOWED_ROOT_FILES = frozenset(
    {
        _DELIVERY_MANIFEST,
        _OPERATOR_MANIFEST,
        "requirements.txt",
        "start.bat",
        "使用说明.md",
    }
)
_ALLOWED_ASSETS = frozenset(
    {
        "igess/reporting/assets/THIRD_PARTY.md",
        "igess/reporting/assets/echarts.min.js",
        "igess/reporting/assets/report.css",
        "igess/reporting/assets/report.js",
    }
)
_FORBIDDEN_SUFFIXES = frozenset({".py", ".pyi", ".map", ".pem", ".key"})
_FORBIDDEN_PARTS = frozenset(
    {".git", ".github", ".pytest_cache", "__pycache__", "tests", "test"}
)
_MAX_DELIVERY_MANIFEST_BYTES = 4 * 1024 * 1024


class ToolkitExportError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolkitExportResult:
    output_root: Path
    tool_version: str
    managed_files: tuple[str, ...]
    removed_files: tuple[str, ...]


def export_operator_toolkit(
    project_root: str | os.PathLike[str],
    output_root: str | os.PathLike[str],
    *,
    tool_version: str | None = None,
    python_command: Sequence[str] | None = None,
    source_root: str | os.PathLike[str] | None = None,
) -> ToolkitExportResult:
    repository = Path(source_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    source_package = repository / "src" / "igess"
    project = Path(project_root).expanduser().resolve(strict=True)
    config_path = project / "economy.yaml"
    if not project.is_dir() or not config_path.is_file():
        raise ToolkitExportError("项目目录必须包含 economy.yaml。")
    output = Path(output_root).expanduser().absolute()
    _validate_output_boundary(repository, output)
    version = tool_version or _project_version(repository)
    command = tuple(python_command or _default_python_command())
    _require_python_311_x64(command)

    config = _load_config(config_path)
    model = config.get("model")
    if not isinstance(model, Mapping):
        raise ToolkitExportError("economy.yaml 缺少 model 配置。")
    model_id = _required_config_text(model, "id")
    engine_id = str(model.get("engine_id", "generic"))
    scenarios_value = config.get("scenarios")
    if not isinstance(scenarios_value, Mapping) or not scenarios_value:
        raise ToolkitExportError("economy.yaml 未定义可发布场景。")
    scenarios = tuple(sorted(str(item) for item in scenarios_value))
    schema_path = _configured_schema(project, config, engine_id)

    with tempfile.TemporaryDirectory(prefix="igess-operator-export-") as temporary:
        staging = Path(temporary) / "candidate"
        staging.mkdir(parents=True)
        _stage_python_sources(source_package, staging / "igess")
        _stage_reporting_assets(source_package, staging / "igess")
        bundle = staging / "bundle"
        bundle.mkdir()
        bundled_config = _distribution_config(config, engine_id)
        (bundle / "economy.yaml").write_text(
            yaml.safe_dump(bundled_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        if schema_path is not None:
            shutil.copyfile(schema_path, bundle / "schema.py")
        _compile_sourceless(staging, command)
        _remove_python_sources(staging)
        _write_root_files(
            staging,
            tool_version=version,
            model_id=model_id,
            engine_id=engine_id,
            scenarios=scenarios,
            has_schema=schema_path is not None,
        )
        managed = tuple(
            sorted(
                {
                    path.relative_to(staging).as_posix()
                    for path in staging.rglob("*")
                    if path.is_file()
                }
                | {_DELIVERY_MANIFEST}
            )
        )
        hashes = {
            relative: _sha256(staging / PurePosixPath(relative))
            for relative in managed
            if relative != _DELIVERY_MANIFEST
        }
        delivery = {
            "schema_version": 1,
            "tool_version": version,
            "managed_files": list(managed),
            "sha256": hashes,
        }
        _write_json(staging / _DELIVERY_MANIFEST, delivery)
        _scan_candidate(
            staging,
            managed,
            forbidden_roots=(repository, project, schema_path.parent if schema_path else None),
        )
        old_managed = _read_old_managed_files(output)
        removed = _synchronize(staging, output, managed, old_managed)
    return ToolkitExportResult(
        output_root=output.resolve(),
        tool_version=version,
        managed_files=managed,
        removed_files=removed,
    )


def scan_operator_candidate(
    root: str | os.PathLike[str],
    *,
    forbidden_roots: Sequence[Path | None] = (),
) -> tuple[str, ...]:
    candidate = Path(root).resolve(strict=True)
    managed = tuple(
        sorted(path.relative_to(candidate).as_posix() for path in candidate.rglob("*") if path.is_file())
    )
    _scan_candidate(candidate, managed, forbidden_roots=forbidden_roots)
    return managed


def _stage_python_sources(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ToolkitExportError(f"IGESS 源码包不存在：{source}")
    module_paths = _python_module_paths(source)
    included = _runtime_dependency_closure(module_paths, "igess.operator_cli")
    for module in sorted(included):
        path = module_paths[module]
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _python_module_paths(source: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in source.rglob("*.py"):
        relative = path.relative_to(source)
        if path.name == "__init__.py":
            suffix = relative.parent.parts
        else:
            suffix = (*relative.parent.parts, path.stem)
        module = ".".join(("igess", *suffix))
        result[module] = path
    return result


def _runtime_dependency_closure(
    module_paths: Mapping[str, Path],
    entrypoint: str,
) -> frozenset[str]:
    if entrypoint not in module_paths:
        raise ToolkitExportError(f"运行入口不存在：{entrypoint}")
    included: set[str] = set()
    pending = [entrypoint]
    while pending:
        module = pending.pop()
        if module in included:
            continue
        path = module_paths.get(module)
        if path is None:
            continue
        included.add(module)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        except (OSError, UnicodeError, SyntaxError) as error:
            raise ToolkitExportError(
                f"无法分析运行依赖 {path.name}：{type(error).__name__}"
            ) from None
        dependencies: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                dependencies.update(
                    alias.name for alias in node.names if alias.name.startswith("igess")
                )
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import(package, node.level, node.module)
                if base:
                    dependencies.add(base)
                    dependencies.update(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
        for dependency in dependencies:
            candidate = dependency
            while candidate:
                if candidate in module_paths and candidate not in included:
                    pending.append(candidate)
                    break
                candidate = candidate.rpartition(".")[0]
        parent = module.rpartition(".")[0]
        while parent.startswith("igess"):
            if parent in module_paths and parent not in included:
                pending.append(parent)
            parent = parent.rpartition(".")[0]
    return frozenset(included)


def _resolved_import(package: str, level: int, module: str | None) -> str | None:
    if level == 0:
        return module if module and module.startswith("igess") else None
    parts = package.split(".")
    trim = level - 1
    if trim > len(parts):
        return None
    anchor = parts[: len(parts) - trim]
    if module:
        anchor.extend(module.split("."))
    resolved = ".".join(anchor)
    return resolved if resolved.startswith("igess") else None


def _stage_reporting_assets(source_package: Path, destination_package: Path) -> None:
    source_assets = source_package / "reporting" / "assets"
    destination_assets = destination_package / "reporting" / "assets"
    destination_assets.mkdir(parents=True, exist_ok=True)
    mapping = {
        "THIRD_PARTY.md": "THIRD_PARTY.md",
        "echarts.min.js": "echarts.min.js",
        "report.css": "report.css",
        "report.min.js": "report.js",
    }
    for source_name, destination_name in mapping.items():
        source = source_assets / source_name
        if not source.is_file():
            raise ToolkitExportError(f"报表生产资产不存在：{source_name}")
        shutil.copyfile(source, destination_assets / destination_name)


def _compile_sourceless(staging: Path, command: Sequence[str]) -> None:
    invocation = [
        *command,
        "-m",
        "compileall",
        "-b",
        "-f",
        "-q",
        "-o",
        "2",
        "-s",
        str(staging),
        "-p",
        "igess-toolkit",
        str(staging / "igess"),
    ]
    schema = staging / "bundle" / "schema.py"
    if schema.is_file():
        invocation.append(str(schema))
    completed = subprocess.run(
        invocation,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise ToolkitExportError(f"Python 3.11 字节码编译失败：{detail}")


def _remove_python_sources(staging: Path) -> None:
    for path in staging.rglob("*.py"):
        path.unlink()
    for directory in sorted(staging.rglob("__pycache__"), reverse=True):
        if directory.is_dir():
            shutil.rmtree(directory)


def _write_root_files(
    staging: Path,
    *,
    tool_version: str,
    model_id: str,
    engine_id: str,
    scenarios: Sequence[str],
    has_schema: bool,
) -> None:
    manifest = {
        "schema_version": 1,
        "tool_version": tool_version,
        "model_id": model_id,
        "engine_id": engine_id,
        "config": "bundle/economy.yaml",
        "schema": "bundle/schema.pyc" if has_schema else None,
        "scenarios": list(scenarios),
    }
    _write_json(staging / _OPERATOR_MANIFEST, manifest)
    (staging / "requirements.txt").write_text(
        "PyYAML==6.0.3\n",
        encoding="utf-8",
        newline="\n",
    )
    (staging / "start.bat").write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "py -3.11 -c \"import struct,sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) and struct.calcsize('P')==8 else 1)\"\r\n"
        "if errorlevel 1 (\r\n"
        "  echo [IGESS] 需要 Windows x64 和 Python 3.11 x64。\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "py -3.11 -c \"import yaml\"\r\n"
        "if errorlevel 1 (\r\n"
        "  echo [IGESS] 缺少依赖，请先执行：py -3.11 -m pip install -r requirements.txt\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "py -3.11 -m igess.operator_cli --bundle \".\"\r\n"
        "if errorlevel 1 pause\r\n",
        encoding="utf-8-sig",
        newline="",
    )
    (staging / "使用说明.md").write_text(
        "# IGESS 数值调优工作台\n\n"
        "## 首次使用\n\n"
        "1. 安装 Windows x64 版 Python 3.11。\n"
        "2. 在本目录执行 `py -3.11 -m pip install -r requirements.txt`。\n"
        "3. 双击 `start.bat`，工作台会在默认浏览器打开。\n\n"
        "## 日常使用\n\n"
        "1. 在自己的数值仓库中修改 `.xlsx` 并导出 JSON。\n"
        "2. 在工作台填写 JSON 目录，选择预设场景并运行。\n"
        "3. 在历史中查看报表、对比和固定回归结果。\n"
        "4. 工具更新时先关闭工作台，再执行 `git pull`。\n\n"
        "工具完全离线，导表目录只读；本地历史位于 `%LOCALAPPDATA%\\IGESS Operator`，不会自动删除。\n",
        encoding="utf-8",
        newline="\n",
    )


def _scan_candidate(
    root: Path,
    managed: Sequence[str],
    *,
    forbidden_roots: Sequence[Path | None],
) -> None:
    actual = tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    )
    if actual != tuple(sorted(managed)):
        raise ToolkitExportError("发布候选包含交付清单之外的文件。")
    forbidden_bytes: set[bytes] = set()
    for path in forbidden_roots:
        if path is None:
            continue
        for text in {str(path), str(path).replace("\\", "/")}:
            forbidden_bytes.add(text.encode("utf-8"))
            forbidden_bytes.add(text.encode("utf-16-le"))
    for relative in actual:
        path = root / PurePosixPath(relative)
        parts = {part.casefold() for part in PurePosixPath(relative).parts}
        suffix = path.suffix.casefold()
        if suffix in _FORBIDDEN_SUFFIXES or parts & _FORBIDDEN_PARTS:
            raise ToolkitExportError(f"发布候选包含禁止文件：{relative}")
        if not _allowed_delivery_path(relative):
            raise ToolkitExportError(f"发布候选包含未获准文件：{relative}")
        encoded = path.read_bytes()
        if any(marker and marker in encoded for marker in forbidden_bytes):
            raise ToolkitExportError(f"发布候选泄露源码或构建绝对路径：{relative}")


def _allowed_delivery_path(relative: str) -> bool:
    if relative in _ALLOWED_ROOT_FILES or relative in _ALLOWED_ASSETS:
        return True
    path = PurePosixPath(relative)
    if relative == "bundle/economy.yaml" or relative == "bundle/schema.pyc":
        return True
    return len(path.parts) >= 2 and path.parts[0] == "igess" and path.suffix == ".pyc"


def _read_old_managed_files(output: Path) -> frozenset[str]:
    manifest = output / _DELIVERY_MANIFEST
    if not manifest.exists():
        return frozenset()
    try:
        if manifest.stat().st_size > _MAX_DELIVERY_MANIFEST_BYTES:
            raise ToolkitExportError("旧交付清单过大，拒绝同步。")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except ToolkitExportError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ToolkitExportError(f"旧交付清单无法读取：{type(error).__name__}") from None
    values = payload.get("managed_files") if isinstance(payload, Mapping) else None
    if not isinstance(values, list):
        raise ToolkitExportError("旧交付清单格式无效。")
    result: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not _safe_relative(value):
            raise ToolkitExportError("旧交付清单包含不安全路径。")
        result.add(value)
    return frozenset(result)


def _synchronize(
    staging: Path,
    output: Path,
    managed: Sequence[str],
    old_managed: frozenset[str],
) -> tuple[str, ...]:
    output.mkdir(parents=True, exist_ok=True)
    resolved_output = output.resolve(strict=True)
    new_managed = frozenset(managed)
    for relative in new_managed:
        target = _target_path(resolved_output, relative)
        if (target.exists() or target.is_symlink()) and relative not in old_managed:
            raise ToolkitExportError(f"新交付文件会覆盖非导出器管理的文件：{relative}")
    for relative in sorted(new_managed):
        source = staging / PurePosixPath(relative)
        target = _target_path(resolved_output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.igess-new")
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    removed: list[str] = []
    for relative in sorted(old_managed - new_managed, reverse=True):
        target = _target_path(resolved_output, relative)
        if target.is_file() or target.is_symlink():
            target.unlink()
            removed.append(relative)
    for directory in sorted(
        {(_target_path(resolved_output, item)).parent for item in old_managed - new_managed},
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        if directory != resolved_output:
            try:
                directory.rmdir()
            except OSError:
                pass
    return tuple(sorted(removed))


def _target_path(root: Path, relative: str) -> Path:
    if not _safe_relative(relative):
        raise ToolkitExportError("交付清单包含不安全路径。")
    target = root / PurePosixPath(relative)
    try:
        target.parent.resolve(strict=False).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise ToolkitExportError("交付路径逃逸输出目录。") from None
    return target


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def _validate_output_boundary(repository: Path, output: Path) -> None:
    try:
        resolved = output.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise ToolkitExportError(f"输出目录无效：{type(error).__name__}") from None
    if resolved == repository or repository.is_relative_to(resolved):
        raise ToolkitExportError("输出目录不能是 IGESS 源码仓库或其父目录。")


def _configured_schema(project: Path, config: Mapping[str, Any], engine_id: str) -> Path | None:
    if engine_id != "fish":
        return None
    engine = config.get("engine")
    value = engine.get("python_schema") if isinstance(engine, Mapping) else None
    if not isinstance(value, str) or not value:
        raise ToolkitExportError("Fish 项目缺少 engine.python_schema。")
    path = Path(value)
    if not path.is_absolute():
        path = project / path
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise ToolkitExportError(f"Fish 生成 schema 不可用：{type(error).__name__}") from None
    if not path.is_file() or path.suffix.casefold() != ".py":
        raise ToolkitExportError("Fish 生成 schema 必须是 .py 文件。")
    return path


def _distribution_config(config: Mapping[str, Any], engine_id: str) -> dict[str, Any]:
    copied = json.loads(json.dumps(config, ensure_ascii=False))
    if engine_id == "fish":
        engine = copied.setdefault("engine", {})
        engine["data_root"] = "__SELECTED_JSON_DIRECTORY__"
        engine["python_schema"] = "bundle/schema.pyc"
    return copied


def _load_config(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ToolkitExportError(f"economy.yaml 无法读取：{type(error).__name__}") from None
    if not isinstance(payload, dict):
        raise ToolkitExportError("economy.yaml 根节点必须是对象。")
    return payload


def _default_python_command() -> tuple[str, ...]:
    if sys.version_info[:2] == (3, 11) and sys.maxsize > 2**32:
        return (sys.executable,)
    if os.name == "nt" and shutil.which("py"):
        return ("py", "-3.11")
    executable = shutil.which("python3.11")
    if executable:
        return (executable,)
    raise ToolkitExportError("找不到 Python 3.11 x64 字节码编译器。")


def _require_python_311_x64(command: Sequence[str]) -> None:
    completed = subprocess.run(
        [
            *command,
            "-c",
            "import json,struct,sys;print(json.dumps({'version':list(sys.version_info[:2]),'bits':struct.calcsize('P')*8}))",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        payload = {}
    if completed.returncode != 0 or payload != {"version": [3, 11], "bits": 64}:
        raise ToolkitExportError("导出器要求可用的 Python 3.11 x64 编译器。")


def _project_version(repository: Path) -> str:
    try:
        import tomllib

        payload = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
        value = payload["project"]["version"]
    except (OSError, KeyError, TypeError, ValueError):
        value = None
    if not isinstance(value, str) or not value:
        raise ToolkitExportError("无法确定 IGESS 工具版本。")
    return value


def _required_config_text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ToolkitExportError(f"economy.yaml 缺少 model.{key}。")
    return item


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


__all__ = [
    "ToolkitExportError",
    "ToolkitExportResult",
    "export_operator_toolkit",
    "scan_operator_candidate",
]

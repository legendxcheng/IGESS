"""Explicit, shallow project catalog for the local development Dashboard."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class DashboardProject:
    key: str
    label: str
    root: Path
    config: Path | None = None
    tables: Path | None = None
    runs_root: Path | None = None


def discover_dashboard_projects(project, config=None, tables=None, runs_root=None):
    """Scan only the launch root and immediate projects/examples; never walk runs."""
    root = Path(project).resolve()
    workspace = root.parent.parent if root.parent.name in {"projects", "examples"} else root
    entries = []
    seen = set()

    def add(path, label, config_override=None, tables_override=None):
        try:
            if path.is_symlink() or path.is_junction():
                return
        except AttributeError:  # Python 3.11 has no is_junction.
            import stat
            if getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return
        resolved = path.resolve()
        selected_config = Path(config_override) if config_override is not None else resolved / "economy.yaml"
        if not selected_config.is_absolute():
            selected_config = resolved / selected_config
        identity = str(selected_config.resolve()).casefold()
        if identity in seen:
            return
        seen.add(identity)
        key = "p-" + sha256(identity.encode()).hexdigest()[:16]
        # Configuration examples have no authoring sources.
        explicit_config = selected_config if config_override is not None or not (resolved / "Datas").is_dir() else None
        selected_tables = Path(tables_override) if tables_override is not None else resolved / (
            "examples/shelldiver_v0/luban_exports" if config_override is not None else "luban_exports"
        )
        if not selected_tables.is_absolute():
            selected_tables = resolved / selected_tables
        entries.append(DashboardProject(
            key, label, resolved, explicit_config,
            selected_tables if explicit_config is not None or tables_override is not None else None,
            Path(runs_root).resolve() / key if runs_root is not None else None,
        ))

    if config is not None or tables is not None or (root / "economy.yaml").is_file():
        launch_config = config
        if config is None and tables is not None:
            launch_config = "examples/shelldiver_v0/economy.yaml"
        add(root, root.name, launch_config, tables)
    for group in ("projects", "examples"):
        directory = workspace / group
        try:
            children = sorted(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if group == "projects" and child.name == "fish":
                continue  # Retired Python backend, never a new simulation target.
            try:
                if child.is_dir() and (child / "economy.yaml").is_file():
                    add(child, child.name + (" · example" if group == "examples" else ""))
            except OSError:
                continue
    if not entries:
        # Preserve the legacy CLI fallback for a standalone unconfigured root.
        add(root, root.name, config or "examples/shelldiver_v0/economy.yaml", tables)
    return tuple(entries)

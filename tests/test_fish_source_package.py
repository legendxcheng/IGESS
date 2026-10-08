from pathlib import Path

import pytest

from igess.fish_source_package import _modules


def write_module(root: Path, name: str, source: str) -> None:
    base = root / "proj" if name.startswith("Script.") else root
    path = base / (name.replace(".", "/") + ".lua")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_dynamic_require_includes_prefix_candidates_and_their_dependencies(tmp_path):
    write_module(tmp_path, "simulation.cli", '''
local function localState(moduleName)
    return require("Script.Application." .. moduleName)
end
return localState("First")
''')
    write_module(tmp_path, "Script.Application.First", 'return require("Script.Domain.Rule")')
    write_module(tmp_path, "Script.Application.Second", 'return {}')
    write_module(tmp_path, "Script.Domain.Rule", 'return {}')
    write_module(tmp_path, "Script.Unrelated.View", 'return {}')
    write_module(tmp_path, "Script.Table.Values", 'return {}')

    assert set(_modules(tmp_path)) == {
        "simulation.cli", "Script.Application.First", "Script.Application.Second",
        "Script.Domain.Rule",
    }


def test_literal_concatenation_still_resolves_one_module(tmp_path):
    write_module(tmp_path, "simulation.cli", 'return require("Script." .. "Domain.Rule")')
    write_module(tmp_path, "Script.Domain.Rule", 'return {}')
    write_module(tmp_path, "Script.Domain.Other", 'return {}')
    assert set(_modules(tmp_path)) == {"simulation.cli", "Script.Domain.Rule"}


@pytest.mark.parametrize("expression", [
    '"Script.Missing"',
    '"Script.Missing." .. moduleName',
])
def test_missing_static_or_dynamic_dependency_still_fails(tmp_path, expression):
    write_module(tmp_path, "simulation.cli", f'return require({expression})')
    with pytest.raises(ValueError, match="Lua runtime dependency unavailable"):
        _modules(tmp_path)

"""Build the source-owned Lua session as a stripped, offline Windows runtime."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from .fish_source_runtime import source_code_digest

RUNTIME_FILES = frozenset({"runtime.luac", "runtime.json", "lua55.exe", "lua55.dll", "LUA-LICENSE.txt"})
LUA_BYTECODE_HEADER = b"\x1bLua\x55"
_REQUIRE = re.compile(r'''\brequire\s*\(?\s*(["'][\w.]+["'](?:\s*\.\.\s*["'][\w.]+["'])*)''')
_LICENSE = """Lua — https://www.lua.org/license.html
Copyright © 1994–2026 Lua.org, PUC-Rio.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


def _modules(root: Path) -> dict[str, Path]:
    available = {
        path.relative_to(root / "proj").with_suffix("").as_posix().replace("/", "."): path
        for path in (root / "proj/Script").rglob("*.lua")
        if not path.is_relative_to(root / "proj/Script/Table")
    }
    available.update({
        path.relative_to(root).with_suffix("").as_posix().replace("/", "."): path
        for path in (root / "simulation").rglob("*.lua")
    })
    included: dict[str, Path] = {}
    pending = ["simulation.cli"]
    while pending:
        name = pending.pop()
        if name in included or name.startswith("Script.Table."):
            continue
        path = available.get(name)
        if path is None:
            raise ValueError(f"Lua runtime dependency unavailable: {name}")
        included[name] = path
        pending.extend(
            "".join(re.findall(r'''["']([\w.]+)["']''', expression))
            for expression in _REQUIRE.findall(path.read_text(encoding="utf-8-sig"))
        )
    return included


def _require_x64_pe(path: Path) -> None:
    value = path.read_bytes()
    try:
        offset = struct.unpack_from("<I", value, 60)[0]
        valid = value[:2] == b"MZ" and value[offset:offset + 4] == b"PE\0\0"
        valid = valid and struct.unpack_from("<H", value, offset + 4)[0] == 0x8664
    except struct.error:
        valid = False
    if not valid:
        raise ValueError(f"Lua runtime must be Windows x64: {path.name}")


def build_fish_source_package(source: Path, destination: Path, lua_executable: str) -> None:
    executable = shutil.which(lua_executable)
    if executable is None:
        raise ValueError("Lua 5.5 compiler/interpreter is unavailable")
    interpreter = Path(executable).resolve(strict=True)
    library = interpreter.with_name("lua55.dll")
    _require_x64_pe(interpreter)
    _require_x64_pe(library)
    version = subprocess.run(
        [str(interpreter), "-e", "assert(_VERSION == 'Lua 5.5'); print(_VERSION)"],
        capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
    ).stdout.strip()
    modules = _modules(source)
    before_digest = source_code_digest(source)
    destination.mkdir(parents=True)
    output = destination / "runtime.luac"
    # The outer chunk contains stripped binary loaders, never embedded Lua text.
    lines = ["local loaders = {}"]
    for name, path in sorted(modules.items()):
        lines.extend([
            "do",
            f"local f = assert(io.open({json.dumps(path.as_posix(), ensure_ascii=False)}, 'rb'))",
            f"local fn = assert(load(f:read('*a'), {json.dumps('=' + name)}, 't')); f:close()",
            ("loaders[#loaders + 1] = string.format('package.preload[%q] = assert(load(%q, %q, %q))', "
             f"{json.dumps(name)}, string.dump(fn, true), {json.dumps('=' + name)}, 'b')"),
            "end",
        ])
    lines.extend([
        "loaders[#loaders + 1] = \"return require('simulation.cli')\"",
        "local entry = assert(load(table.concat(loaders, '\\n'), '=fish-runtime', 't'))",
        f"local output = assert(io.open({json.dumps(output.as_posix(), ensure_ascii=False)}, 'wb'))",
        "output:write(string.dump(entry, true)); output:close()",
    ])
    with tempfile.TemporaryDirectory(prefix="igess-lua-build-") as temporary:
        compiler = Path(temporary) / "compile.lua"
        compiler.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        subprocess.run(
            [str(interpreter), str(compiler)], capture_output=True, text=True,
            encoding="utf-8", timeout=60, check=True,
        )
    if not output.read_bytes().startswith(LUA_BYTECODE_HEADER):
        raise ValueError("Lua compiler did not emit Lua 5.5 bytecode")
    if source_code_digest(source) != before_digest:
        raise ValueError("Lua source changed during packaging")
    shutil.copyfile(interpreter, destination / "lua55.exe")
    shutil.copyfile(library, destination / "lua55.dll")
    (destination / "LUA-LICENSE.txt").write_text(_LICENSE, encoding="utf-8", newline="\n")
    manifest = {
        "format": 1, "lua_version": version, "platform": "windows-x64",
        "source_code_sha256": before_digest,
        "modules": sorted(modules), "numeric_input": "selected-json-only",
        "sha256": {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                   for name in sorted(RUNTIME_FILES - {"runtime.json"})},
    }
    (destination / "runtime.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )

"""Complete logical observations through the real source runtime boundary."""
from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path

import pytest

from igess.fish_source_runtime import FishSourceRuntime, FishSourceRejection, FishSourceRuntimeError

SOURCE = Path(os.environ.get("FISH_SOURCE_ROOT", str(Path(__file__).resolve().parents[2] / "fish-oasis")))


def test_observations_equal_complete_queries_and_remain_independent() -> None:
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as runtime:
        runtime.create(start_at=0, random_seed=7, in_fishing_area=True, fast_advance=True)
        history = runtime.checkpoint()
        first = runtime.observe(include_luck=True)
        assert first == runtime.request({"op": "query", "includeLuck": True})
        expected = runtime.request({"op": "query", "includeLuck": True})
        first["inventory"]["items"].append({"corrupted": True})
        first["wallet"]["money"]["coeff"] = "999999"
        assert runtime.observe(include_luck=True) == expected
        assert runtime.checkpoint() == history
        runtime.request({"op": "advance", "time": 30})
        assert runtime.observe(include_luck=False) == runtime.request({"op": "query", "includeLuck": False})
        assert expected["time"] == 0
        saved = runtime.checkpoint()
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as runtime:
        runtime.restore(saved)
        assert runtime.observe() == runtime.request({"op": "query"})


def test_change_transport_resynchronizes_and_never_replays_commands() -> None:
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as runtime:
        runtime.create(start_at=0, random_seed=7)
        history = runtime.checkpoint()
        first = runtime.request({"op": "query_changes", "channel": "one", "base": 0})
        assert first["kind"] == "full"
        delta = runtime.request({"op": "query_changes", "channel": "one", "base": first["token"], "includeLuck": False})
        assert delta["kind"] == "delta" and "luck" in delta["patch"]["removed"]
        for channel, base in (("two", delta["token"]), ("one", first["token"])):
            response = runtime.request({"op": "query_changes", "channel": channel, "base": base})
            assert response["kind"] == "full"
            assert response["state"] == runtime.request({"op": "query"})
        with pytest.raises(FishSourceRejection, match="simulation_query_options_invalid"):
            runtime.request({"op": "query_changes", "channel": "one", "includeLuck": "bad"})
        assert runtime.checkpoint() == history


def test_rejected_session_replacement_preserves_observation_baseline() -> None:
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as runtime:
        runtime.create(start_at=0, random_seed=7, fast_advance=True)
        runtime.observe()
        saved = runtime.checkpoint()
        runtime.request({"op": "advance", "time": 30})
        current = runtime.observe()
        assert current["time"] == 30
        with pytest.raises(FishSourceRejection, match="simulation_session_exists"):
            runtime.restore(saved)
        assert runtime.observe() == current
        with pytest.raises(FishSourceRejection, match="simulation_session_exists"):
            runtime.create(start_at=0, random_seed=7, fast_advance=True)
        assert runtime.observe() == current


def test_observation_inventory_mutations_and_offline_recovery() -> None:
    script = "package.path='./?.lua;./proj/?.lua;'..package.path; local s=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0)); io.write(require('simulation.Json').Encode(s))"
    state = json.loads(subprocess.check_output(["lua55", "-e", script], cwd=SOURCE, text=True, encoding="utf-8"))
    state["wallet"]["money"] = {"sign": 1, "coeff": "1", "exp": 90}
    state["fish"]["items"] = [
        {"instanceId": i, "fishId": 101, "mutationId": 1, "weightGram": 1000, "level": 1, "hallSlot": 0}
        for i in range(1, 4)
    ]
    state["fish"]["nextInstanceId"] = 4
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as runtime:
        runtime.create(start_at=0, initial_state=state, random_seed=7, fast_advance=True)
        original = runtime.observe()
        for i in range(1, 4):
            runtime.request({"op": "sell_fish", "instanceId": i, "requestId": f"sell:{i}"})
            assert runtime.observe() == runtime.request({"op": "query"})
        assert original["inventory"]["total"] == 3
        assert runtime.observe()["inventory"]["items"] == []
        runtime.request({"op": "go_offline"})
        runtime.request({"op": "advance", "time": 600})
        observed = runtime.observe()
        saved = runtime.checkpoint()
    with FishSourceRuntime(SOURCE, SOURCE / "igess_export/json") as restored:
        restored.restore(saved)
        assert restored.observe() == observed


@pytest.mark.parametrize("fault", ["base", "token", "conflict", "legacy"])
def test_runtime_handles_external_observation_protocol_boundaries(tmp_path: Path, fault: str) -> None:
    # A real external Lua peer supplies deliberately bad wire responses. No
    # decoder internals are mocked; recovery must use reads, never commands.
    (tmp_path / "proj/Script").mkdir(parents=True)
    (tmp_path / "simulation").mkdir()
    (tmp_path / "data").mkdir()
    fixture = r'''
local serial=0
for line in io.lines() do
    local value
    if line:find('"op":"capabilities"',1,true) then
        value='{"protocol":2,"checkpointFormat":1,"luaVersion":"Lua 5.5"CAPABILITY}'
    elseif line:find('"op":"query"',1,true) then
        value='{"time":0,"inventory":{"items":[1]}}'
    elseif line:find('"op":"query_changes"',1,true) then
        serial=serial+1
        local channel=line:match('"channel":"([a-f0-9]+)"')
        if serial==2 then
            value='{"channel":"'..channel..'","token":TOKEN,"base":BASE,"kind":"delta",'
                ..'"patch":{"values":VALUES,"removed":REMOVED,"sections":[]}}'
        else
            value='{"channel":"'..channel..'","token":'..serial..',"base":0,"kind":"full",'
                ..'"state":{"time":0,"inventory":{"items":[1]}}}'
        end
    else error('observation recovery attempted a command') end
    io.write('{"ok":true,"value":'..value..'}\n');io.flush()
end
'''
    fixture = (fixture.replace("CAPABILITY", "" if fault == "legacy" else ',"observationChangesVersion":1')
               .replace("TOKEN", "true" if fault == "token" else "2")
               .replace("BASE", "999" if fault == "base" else "1")
               .replace("VALUES", '{"time":1}' if fault == "conflict" else "[]")
               .replace("REMOVED", '["time"]' if fault == "conflict" else "[]"))
    (tmp_path / "simulation/cli.lua").write_text(fixture, encoding="utf-8")
    with FishSourceRuntime(tmp_path, tmp_path / "data") as runtime:
        first = runtime.observe()
        assert first == {"time": 0, "inventory": {"items": [1]}}
        if fault != "legacy":
            with pytest.raises(FishSourceRuntimeError, match="simulation_observation_invalid"):
                runtime.observe()
        assert runtime.observe() == first

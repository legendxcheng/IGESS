"""The source player's available purchases follow the current game catalog."""
import json
import os
import shutil
import subprocess
from pathlib import Path

from igess.fish_source_runtime import FishSourceRuntime

SOURCE = Path(os.environ.get("FISH_SOURCE_ROOT", str(Path(__file__).resolve().parents[2] / "fish-oasis")))


def test_torpedo_quotes_follow_unlock_and_selected_export_visibility(tmp_path):
    selected = tmp_path / "selected"
    shutil.copytree(SOURCE / "igess_export/json", selected)
    path = selected / "tbtorpedo.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    for index, row in enumerate(rows):
        row["isOpen"] = index % 2 == 0
    path.write_text(json.dumps(rows), encoding="utf-8")
    script = '''package.path='./?.lua;./proj/?.lua;'..package.path
local state=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0))
state.wallet.strength={sign=1,coeff='3',exp=9}
state.torpedo.ownedIds={1,2}
io.write(require('simulation.Json').Encode(state))'''
    state = json.loads(subprocess.check_output(["lua55", "-e", script], cwd=SOURCE, text=True, encoding="utf-8"))
    with FishSourceRuntime(SOURCE, selected) as host:
        host.create(start_at=0, initial_state=state, in_fishing_area=True, random_seed=42)
        assert host.request({"op": "query_actions"})["torpedoes"] == []
        host.request({"op": "prepare_throw", "requestId": "unlock-shop"})
        host.request({"op": "begin_throw_flight", "requestId": "unlock-shop"})
        host.request({"op": "advance", "time": 10})
        host.request({"op": "select_throw_landing", "requestId": "unlock-shop", "distanceCm": 21001})
        host.request({"op": "finalize_throw_landing", "requestId": "unlock-shop"})
        # The unlock changes before fish inventory changes. Quote caching must
        # therefore include eligibility, not just fish and hall level.
        assert host.request({"op": "query"})["trashMan"]["unlocked"] is True
        quotes = host.request({"op": "query_actions"})["torpedoes"]
        assert {quote["torpedoId"] for quote in quotes} == {row["id"] for row in rows if row["isOpen"]}
        assert host.request({"op": "query_actions"})["torpedoes"] == quotes
        host.request({"op": "complete_throw", "requestId": "unlock-shop"})
        current = host.request({"op": "query"})
        host.request({"op": "select_torpedo", "requestId": "use-owned-closed", "torpedoId": 2, "revision": current["revision"]})
        assert host.request({"op": "query"})["torpedo"]["selectedId"] == 2
        host.request({"op": "prepare_throw", "requestId": "throw-owned-closed"})

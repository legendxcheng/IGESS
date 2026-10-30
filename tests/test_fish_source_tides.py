"""Single tide at the public source session and formal workflow boundaries."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from igess.authoring.service import AuthoringService
from igess.fish_source_runtime import FishSourceRuntime

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('FISH_SOURCE_ROOT',str(ROOT.parent/'fish-oasis')))

def initial_state():
    script="""package.path='./?.lua;./proj/?.lua;'..package.path
local s=assert(require('Script.Domain.Player.PlayerArchiveSchema').New(0))
s.wallet.material={sign=1,coeff='3',exp=2}
s.combat.ownedGunIds={10001};s.combat.equippedGunId=10001;s.combat.lastSelectedGunId=10001
s.fish.items={{instanceId=1,fishId=101,mutationId=1,weightGram=1000,level=1,hallSlot=1}}
s.fish.nextInstanceId=2
io.write(require('simulation.Json').Encode(s))"""
    return json.loads(subprocess.check_output(['lua55','-e',script],cwd=SOURCE,text=True,encoding='utf-8'))

def test_mid_tide_replay_preserves_costs_and_five_random_eggs():
    with FishSourceRuntime(SOURCE,SOURCE/'igess_export/json') as original:
        original.create(start_at=0,initial_state=initial_state(),random_seed=37)
        admitted=original.request({'op':'start_tide','roundId':'round:1'})
        assert admitted['success'] and len(admitted['reloads'])==6
        original.request({'op':'advance','time':60})
        checkpoint=original.checkpoint()
        before=original.request({'op':'query'})
        assert before['eggs']['items']==[]
        original.request({'op':'advance','time':120})
        completed=original.request({'op':'complete_tide','roundId':'round:1'})
        expected=original.request({'op':'query'})
    with FishSourceRuntime(SOURCE,SOURCE/'igess_export/json') as restored:
        assert restored.restore(checkpoint)==before
        assert restored.request({'op':'start_tide','roundId':'round:1'})['materialSpent']['sign']==0
        restored.request({'op':'advance','time':120})
        assert restored.request({'op':'complete_tide','roundId':'round:1'})==completed
        assert restored.request({'op':'query'})==expected
        assert len(expected['eggs']['items'])==5 and expected['wallet']['material']['sign']==0

def project(tmp_path,duration):
    target=tmp_path/'fish_source';target.mkdir()
    for name in ('Datas','luban_exports'):
        shutil.copytree(ROOT/'projects/fish_source'/name,target/name)
    config=yaml.safe_load((ROOT/'projects/fish_source/economy.yaml').read_text(encoding='utf-8'))
    # These fixtures isolate tide lifecycle; growth-first admission has its own suite.
    config['player_profiles']['default']['behavior_weights'] = {}
    config['engine']['source_runtime'].update(project_root=str(SOURCE),data_root=str(SOURCE/'igess_export/json'))
    config['scenarios']['smoke']['duration_hours']=str(duration/3600)
    (target/'economy.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
    return target

@pytest.mark.parametrize('duration',[60,120])
def test_formal_single_tide_occupies_time_and_reports_actual_cost(tmp_path,monkeypatch,duration):
    create=FishSourceRuntime.create
    def fixture(self,**kwargs):
        kwargs['initial_state']=initial_state()
        return create(self,**kwargs)
    monkeypatch.setattr(FishSourceRuntime,'create',fixture)
    target=project(tmp_path,duration)
    response=AuthoringService(target).simulate('smoke')
    assert response.ok,response.details
    output=Path(response.result['output_dir'])
    events=json.loads((output/'events.json').read_text(encoding='utf-8'))
    starts=[e for e in events if e['kind']=='start_tide']
    assert len(starts)==1
    assert not any(e['kind'] in {'prepare_throw','start_exercise','collect_slot','claim_fish_reward'} for e in events)
    last=json.loads((output/'timeline.json').read_text(encoding='utf-8'))[-1]
    assert last['resources']['online_tide_reload_material_cumulative']=='300'
    assert last['resources']['online_resource_acquired_cumulative']=='0'
    assert last['resources']['online_money_acquired_cumulative']!='0'
    checkpoint=json.loads((output/'final_checkpoint.json').read_text(encoding='utf-8'))
    if duration==60:
        assert checkpoint['behavior_state']['pending_tide']['endsAt']==120
        assert last['resources']['egg_inventory_count']=='0'
    else:
        assert checkpoint['behavior_state']['pending_tide'] is None
        assert last['resources']['egg_inventory_count']=='5'
    behavior=json.loads((output/'source_behavior.json').read_text(encoding='utf-8'))['profiles']['default']
    assert behavior['tide_rounds'][0]['roundId']=='room:0:round:0'
    assert behavior['tide_rounds'][0]['occupied_seconds']==duration
    manifest=json.loads((output/'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['source_runtime']['tide_policy']['reloads']==6
    report=json.loads((Path(response.result['report_index']).parent/'report_data.json').read_text(encoding='utf-8'))
    assert report['fish_progression']['actions']['default']['tide_rounds']==behavior['tide_rounds']
    resumed=AuthoringService(target).simulate('smoke',checkpoint_input=output/'final_checkpoint.json')
    assert resumed.ok,resumed.details
@pytest.mark.parametrize('cost', [0,-1])
def test_reload_price_zero_is_valid_and_negative_is_diagnosed(tmp_path,cost):
    data=tmp_path/'export';shutil.copytree(SOURCE/'igess_export/json',data)
    path=data/'tbgun.json';rows=json.loads(path.read_text(encoding='utf-8'))
    rows[0]['reloadResourceCost']={'sign':cost,'digits':'0' if cost==0 else '1','scale':0}
    path.write_text(json.dumps(rows),encoding='utf-8')
    with FishSourceRuntime(SOURCE,data) as runtime:
        if cost<0:
            from igess.fish_source_runtime import FishSourceRejection
            with pytest.raises(FishSourceRejection):
                runtime.create(start_at=0,initial_state=initial_state())
        else:
            runtime.create(start_at=0,initial_state=initial_state())
            r=runtime.request({'op':'start_tide','roundId':'free-config'})
            assert r['success'] and len(r['reloads'])==6 and r['materialSpent']['sign']==0
            assert runtime.request({'op':'query'})['wallet']['material']=={'sign':1,'coeff':'3','exp':2}


def test_formal_recurring_rounds_use_source_interval(tmp_path, monkeypatch):
    create = FishSourceRuntime.create
    def fixture(self, **kwargs):
        state = initial_state()
        state["wallet"]["material"] = {"sign": 1, "coeff": "9", "exp": 2}
        kwargs["initial_state"] = state
        return create(self, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, "create", fixture)
    target = project(tmp_path, 301)
    data = tmp_path / "export"
    shutil.copytree(SOURCE / "igess_export/json", data)
    path = data / "tbfishtideconfig.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["intervalSeconds"] = 180
    path.write_text(json.dumps(rows), encoding="utf-8")
    config_path = target / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"]["data_root"] = str(data)
    config["player_profiles"]["default"]["behavior_weights"] = {}
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    response = AuthoringService(target).simulate("smoke")
    assert response.ok, response.details
    output = Path(response.result["output_dir"])
    behavior = json.loads((output / "source_behavior.json").read_text(encoding="utf-8"))["profiles"]["default"]
    rounds = behavior["tide_rounds"]
    assert [(r["openedAt"], r["phase"]) for r in rounds] == [(0, "completed"), (180, "completed")]
    assert sum(len(r["eggs"]) for r in rounds) == 10
    assert all(r["occupied_seconds"] == 120 for r in rounds)
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_runtime"]["tide_schedule"] == {
        "policy": "absolute_opening_only_v1", "room_origin_seconds": 0,
        "interval_seconds": 180, "spawn_window_seconds": 120,
    }


def configured_project(tmp_path, duration, *, interval=180, online=7200, origin=0, sample=30, mode="equivalent_batch_v1", weights=None):
    target = project(tmp_path, duration)
    data = tmp_path / "export"
    shutil.copytree(SOURCE / "igess_export/json", data)
    path = data / "tbfishtideconfig.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["intervalSeconds"] = interval
    rows[0]["spawnWindowSeconds"] = min(120, interval)
    path.write_text(json.dumps(rows), encoding="utf-8")
    config_path = target / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["engine"]["source_runtime"].update(data_root=str(data), room_origin_seconds=origin, advance_mode=mode)
    config["player_profiles"]["default"]["behavior_weights"] = weights or {}
    session = config["player_profiles"]["default"]["session_pattern"]
    config["session_patterns"][session]["daily_online_seconds"] = online
    config["scenarios"]["smoke"]["record_interval_seconds"] = sample
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return target


def fixture_player(monkeypatch, *, strength=None, gun=True):
    create = FishSourceRuntime.create
    def fixture(self, **kwargs):
        state = initial_state()
        state["wallet"]["material"] = {"sign": 1, "coeff": "1", "exp": 6}
        if strength is not None:
            state["wallet"]["strength"] = strength
        if not gun:
            state["combat"]["ownedGunIds"] = []
            state["combat"]["equippedGunId"] = 0
            state["combat"]["lastSelectedGunId"] = 0
        kwargs["initial_state"] = state
        return create(self, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, "create", fixture)


def formal(target, checkpoint=None):
    response = AuthoringService(target).simulate("smoke", checkpoint_input=checkpoint)
    assert response.ok, response.details
    output = Path(response.result["output_dir"])
    def read(name):
        return json.loads((output / name).read_text(encoding="utf-8"))
    return output, read("source_behavior.json")["profiles"]["default"], read("events.json"), read("final_checkpoint.json")


@pytest.mark.parametrize("online,phase,reason", [(299, "skipped", "insufficient_online_time"), (300, "completed", None)])
def test_tide_requires_120_planned_online_seconds(tmp_path, monkeypatch, online, phase, reason):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 301, online=online)
    _, behavior, _, _ = formal(target)
    assert [(r["openedAt"], r["phase"], r.get("reason")) for r in behavior["tide_rounds"]] == [
        (0, "completed", None), (180, phase, reason),
    ]


def test_offline_rounds_are_reported_and_reconnect_does_not_reset_room(tmp_path, monkeypatch):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 86581, interval=3600, online=120, sample=300)
    _, behavior, events, _ = formal(target)
    rounds = behavior["tide_rounds"]
    assert len(rounds) == 25
    assert [(r["openedAt"], r["phase"]) for r in rounds if r["phase"] != "skipped"] == [(0, "completed"), (86400, "completed")]
    assert all(r["reason"] == "offline" for r in rounds[1:24])
    assert not any(e["kind"] in {"start_tide", "claim_fish_reward"} and e["time_seconds"] in {120, 86520} for e in events)


def test_busy_natural_flight_skips_opening_without_time_reversal(tmp_path, monkeypatch):
    fixture_player(monkeypatch, strength={"sign": 1, "coeff": "3", "exp": 9})
    target = configured_project(tmp_path, 100, interval=60, origin=31, weights={"manual_throw": "1"})
    config_path = target / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["player_profiles"]["default"]["behavior_durations"]["manual_throw"]["seconds"] = 1
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    _, behavior, events, _ = formal(target)
    assert behavior["tide_rounds"][0]["openedAt"] == 31
    assert behavior["tide_rounds"][0]["reason"] == "foreground_busy"
    assert not any(e["kind"] == "source_rejected" for e in events)
    times = [e["time_seconds"] for e in events]
    assert times == sorted(times)


def test_known_throw_duration_does_not_cross_opening_or_earn_early_reward(tmp_path, monkeypatch):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 141, origin=20, weights={"manual_throw": "1"})
    _, behavior, events, _ = formal(target)
    assert behavior["tide_rounds"][0]["openedAt"] == 20
    assert not any(e["kind"] == "prepare_throw" and e["time_seconds"] < 20 for e in events)


def test_tide_business_events_do_not_depend_on_sampling_or_advance_mode(tmp_path, monkeypatch):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 301, sample=30)
    first_output, first_behavior, first_events, first_checkpoint = formal(target)
    config_path = target / "economy.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["scenarios"]["smoke"]["record_interval_seconds"] = 7
    config["engine"]["source_runtime"]["advance_mode"] = "accurate"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    _, behavior, events, checkpoint = formal(target)
    assert behavior == first_behavior
    assert events == first_events
    assert checkpoint["behavior_state"]["online_acquisition"] == first_checkpoint["behavior_state"]["online_acquisition"]


def test_invalid_periodic_config_is_diagnosed_before_formal_run(tmp_path):
    target = configured_project(tmp_path, 10, interval=180.5)
    response = AuthoringService(target).simulate("smoke")
    assert not response.ok
    assert response.code == "simulation_tide_config_invalid"
    assert not list((target / "runs").glob("*"))


def test_short_source_interval_records_busy_round_and_completes_before_next_opening(tmp_path, monkeypatch):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 241, interval=60)
    _, behavior, events, _ = formal(target)
    assert [(r["openedAt"], r["phase"], r.get("reason")) for r in behavior["tide_rounds"]] == [
        (0, "completed", None), (60, "skipped", "foreground_busy"),
        (120, "completed", None), (180, "skipped", "foreground_busy"),
        (240, "participating", None),
    ]
    at_120 = [e["kind"] for e in events if e["time_seconds"] == 120]
    assert at_120.index("complete_tide") < at_120.index("start_tide")
    assert sum(e["kind"] == "start_tide" for e in events) == 3


def test_formal_multiple_checkpoints_continue_same_model_without_duplicate_rounds(tmp_path, monkeypatch):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 361, sample=30)
    continuous_output, continuous_behavior, continuous_events, continuous_checkpoint = formal(target)
    checkpoints = []
    segments = []
    previous = None
    for until in (60, 120, 179, 240, 361):
        response = AuthoringService(target).simulate("smoke", until_seconds=until, checkpoint_input=previous)
        assert response.ok, response.details
        output = Path(response.result["output_dir"])
        previous = output / "final_checkpoint.json"
        checkpoint = json.loads(previous.read_text(encoding="utf-8"))
        checkpoints.append(checkpoint)
        segments.extend(json.loads((output / "events.json").read_text(encoding="utf-8")))
        manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        assert manifest["execution_window"]["requested_until_seconds"] == until
        assert manifest["execution_window"]["scenario_end_seconds"] == 361
    assert checkpoints[0]["behavior_state"]["pending_tide"]["endsAt"] == 120
    assert checkpoints[1]["behavior_state"]["pending_tide"] is None
    assert checkpoints[-1]["behavior_state"] == continuous_checkpoint["behavior_state"]
    def commands(events):
        return [e for e in events if e["details"].get("source") != "observation" and e["kind"] not in {"gun_milestone", "egg_admitted", "egg_hatched"}]
    assert commands(segments) == commands(continuous_events)
    assert checkpoints[-1]["model_digest"] == continuous_checkpoint["model_digest"]
    # Formal timeline includes cumulative exact balances after each restored segment.
    final_rows = json.loads((output / "timeline.json").read_text(encoding="utf-8"))
    continuous_rows = json.loads((continuous_output / "timeline.json").read_text(encoding="utf-8"))
    assert final_rows[-1] == continuous_rows[-1]


@pytest.mark.parametrize("until", [-1, 0, True, 362])
def test_invalid_execution_cutoff_is_diagnosed_without_reserving_run(tmp_path, until):
    target = configured_project(tmp_path, 361)
    response = AuthoringService(target).simulate("smoke", until_seconds=until)
    assert not response.ok
    assert response.code == "execution_window_invalid"
    assert not list((target / "runs").glob("*"))


def test_exercise_settles_at_opening_and_pauses_for_entire_tide(tmp_path, monkeypatch):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 151, origin=31, weights={"exercise_barbell": "1"})
    output, behavior, events, _ = formal(target)
    at_opening = [e["kind"] for e in events if e["time_seconds"] == 31]
    assert at_opening.index("stop_exercise") < at_opening.index("start_tide")
    assert behavior["tide_rounds"][0]["occupied_seconds"] == 120
    assert not any(e["kind"] in {"start_exercise", "prepare_throw"} and 31 <= e["time_seconds"] < 151 for e in events)
    rows = json.loads((output / "timeline.json").read_text(encoding="utf-8"))
    strengths = {r["resources"]["strength"] for r in rows if 31 <= r["time_seconds"] <= 151}
    assert len(strengths) == 1


@pytest.mark.parametrize("behavior", ["manual_throw", "exercise_barbell"])
def test_formal_resume_keeps_ordinary_foreground_occupation(tmp_path, monkeypatch, behavior):
    fixture_player(monkeypatch)
    target = configured_project(tmp_path, 151, origin=31, weights={behavior: "1"})
    output, _, events, expected = formal(target)
    first = AuthoringService(target).simulate("smoke", until_seconds=15)
    assert first.ok, first.details
    checkpoint = Path(first.result["output_dir"]) / "final_checkpoint.json"
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["behavior_state"]["pending_throw" if behavior == "manual_throw" else "pending_action"] is not None
    resumed_output, _, after_events, actual = formal(target, checkpoint)
    assert actual["behavior_state"] == expected["behavior_state"]
    first_events = json.loads((checkpoint.parent / "events.json").read_text(encoding="utf-8"))
    assert first_events + after_events == events
    assert json.loads((resumed_output / "timeline.json").read_text(encoding="utf-8"))[-1] == json.loads((output / "timeline.json").read_text(encoding="utf-8"))[-1]

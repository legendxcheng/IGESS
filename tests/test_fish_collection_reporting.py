"""Collection growth through the public static-report artifact boundary."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest

from igess.reporting.static import generate_static_report
from test_source_fish_reporting import _source_run


def unlock(time, fish, mutation):
    return {"profile_id": "default", "time_seconds": time,
            "kind": "codex_fish_unlocked", "item_id": f"{fish}:{mutation}",
            "details": {"source": "observation", "receipt": json.dumps({
                "collectionKey": f"{fish}:{mutation}", "fishId": fish, "mutationId": mutation,
            })}}


def gun(time, kind, identity):
    return {"profile_id": "default", "time_seconds": time, "kind": "gun_milestone",
            "item_id": str(identity), "details": {"kind": kind,
                "identity": f"{kind}:{identity}", "online_time_seconds": str(time)}}


def report(tmp_path, events, scope=None, start=0):
    run = _source_run(tmp_path)
    (run / "events.json").write_text(json.dumps(events), encoding="utf-8")
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    if scope is not None:
        manifest["source_profiles"] = {"default": scope}
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if start:
        timeline = json.loads((run / "timeline.json").read_text(encoding="utf-8"))
        timeline[0]["time_seconds"] = start
        (run / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    index = generate_static_report(run, tmp_path / "report")
    return json.loads((index.parent / "report_data.json").read_text(encoding="utf-8"))


def test_collection_and_guns_count_facts_not_labels_or_reward_steps(tmp_path):
    data = report(tmp_path, [
        unlock(1, 101, 1), unlock(2, 101, 1), unlock(3, 101, 2),
        unlock(4, 101, 2), unlock(5, 101, 3),
        unlock(6, 102, 2), unlock(7, 102, 1), unlock(8, 102, 2),
        gun(10, "normal_codex_completed", 1001),
        gun(12, "gun_claimed", 1001), gun(12, "gun_owned", 1),
        gun(13, "gun_equipped", 1), gun(14, "gun_owned", 1),
    ])
    growth = data["fish_progression"]["persistent"]["profiles"]["default"]
    rows = growth["rows"]
    assert len(rows) == 6
    assert [r["active_time_seconds"] for r in rows] == [1, 3, 5, 6, 10, 12]
    assert rows[3]["progression_categories"] == ["new_fish_species", "new_fish_variant"]
    assert rows[3]["fish_id"] == 102 and rows[3]["mutation_id"] == 2
    assert len({r["event_identity"] for r in rows}) == 6
    assert growth["summary"]["total_progression_count"]["exact_value"] == "6"
    assert growth["summary"]["max_interval_seconds"]["exact_value"] == "4"
    assert growth["days"][0]["event_count"]["exact_value"] == "6"
    assert growth["weeks"][0]["event_count"]["exact_value"] == "6"


@pytest.mark.parametrize("known", [True, False])
def test_resumed_report_uses_initial_history_and_marks_missing_coverage(tmp_path, known):
    scope = {"initial_online": True, "initial_active_time_seconds": 10}
    if known:
        scope["collection_growth"] = {"version": 1, "initial_unlocked_entries": [
            {"fishId": 101, "mutationId": 1}, {"fishId": 102, "mutationId": 2}],
            "initial_gun_facts": ["gun_owned:1"]}
    data = report(tmp_path, [unlock(11, 101, 2), unlock(12, 102, 1),
                             unlock(13, 103, 2), gun(14, "gun_owned", 1)], scope, start=10)
    growth = data["fish_progression"]["persistent"]["profiles"]["default"]
    collection = [r for r in growth["rows"] if r["source_event_kind"] == "codex_fish_unlocked"]
    assert len(collection) == 2
    assert collection[0]["progression_categories"] == ["new_fish_variant"]
    assert collection[1]["progression_categories"] == (
        ["new_fish_species", "new_fish_variant"] if known else ["new_fish_variant"])
    assert growth["collection_coverage"]["first_species_complete"] is known
    if known:
        assert len(growth["rows"]) == 2  # Already-owned gun is not new.
    else:
        assert "未记录" in growth["collection_coverage"]["note"]


def test_same_batch_combinations_have_one_species_and_saved_names(tmp_path):
    scope = {'collection_growth': {'version': 1, 'initial_unlocked_entries': [],
             'initial_gun_facts': [], 'display_names': {
                 'fish': {'101': '历史鱼名'}, 'mutation': {'2': '黄金', '3': '钻石'},
                 'gun': {'1': '历史枪名'}}}}
    data = report(tmp_path, [unlock(1, 101, 3), unlock(1, 101, 2), gun(1, 'gun_owned', 1)], scope)
    rows = data['fish_progression']['persistent']['profiles']['default']['rows']
    assert len(rows) == 3
    assert rows[0]['mutation_id'] == 2
    assert rows[0]['progression_categories'] == ['new_fish_species', 'new_fish_variant']
    assert rows[1]['progression_categories'] == ['new_fish_variant']
    assert rows[0]['same_observation_batch'] is True
    assert rows[0]['display_name'] == '历史鱼名 · 黄金'
    assert rows[2]['gun_id'] == 1 and rows[2]['display_name'] == '历史枪名'


def test_separate_observations_in_same_second_preserve_source_order(tmp_path):
    first, second = unlock(1, 101, 2), unlock(1, 101, 1)
    for event in (first, second):
        event['details']['observation_batch_size'] = '1'
    data = report(tmp_path, [first, second])
    rows = data['fish_progression']['persistent']['profiles']['default']['rows']
    assert len(rows) == 1
    assert rows[0]['mutation_id'] == 2
    assert rows[0]['progression_categories'] == ['new_fish_species', 'new_fish_variant']
    assert rows[0]['same_observation_batch'] is False


def test_growth_at_adjacent_session_boundary_is_counted_in_one_period(tmp_path):
    events = [
        {"profile_id": "default", "time_seconds": 10, "kind": kind, "item_id": "", "details": {}}
        for kind in ('go_offline', 'go_online')]
    data = report(tmp_path, [*events, unlock(10, 101, 1)])
    growth = data['fish_progression']['persistent']['profiles']['default']
    assert [d['event_count']['exact_value'] for d in growth['days']] == ['0', '1']
    assert growth['summary']['total_progression_count']['exact_value'] == '1'
    assert growth['summary']['complete_online_sessions_without_progression']['exact_value'] == '1'


@pytest.mark.parametrize("asset", ["report.js", "report.min.js"])
def test_report_renders_both_labels_one_event_and_readable_identity(tmp_path, asset):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the report frontend")
    report(tmp_path, [unlock(1, 102, 2), gun(2, 'normal_codex_completed', 1001), gun(3, 'gun_owned', 1),
                     {"profile_id": "default", "time_seconds": 4, "kind": "fish_pool_entered",
                      "item_id": "2", "details": {"source": "observation", "receipt": json.dumps({
                          "pool_id": 2, "display_name": "洗脚大盆", "previous_upper_bound": "50", "strength": "51"})}}])
    harness = r'''
const fs = require('fs'), vm = require('vm');
const data = fs.readFileSync(process.argv[1], 'utf8');
const elements = {}, options = {};
const element = key => elements[key] || (elements[key] = {
  id: key, hidden: true, innerHTML: '', textContent: '', dataset: {},
  classList: {toggle() {}}, addEventListener() {},
  querySelector: s => element(key + ' ' + s), querySelectorAll: () => [],
  closest: () => element(key + ' section'),
});
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  document: {querySelector: element, getElementById: id =>
    id === 'igess-report-data' ? {textContent: data} : element(id)},
  window: {addEventListener() {}}, console,
  echarts: {init: target => ({setOption: o => options[target.id] = o, dispose() {}, resize() {}})},
});
setImmediate(() => {
  const chart = options['daily-progression-chart-0'];
  const tips = chart.series.flatMap(s => s.data.map(d => chart.tooltip.formatter({data: d})));
  console.log(JSON.stringify({elements, chart, tips}));
});
'''
    result = subprocess.run([node, '-e', harness, str(tmp_path / 'report/report_data.json'),
                             str(Path('src/igess/reporting/assets') / asset)],
                            text=True, encoding='utf-8', capture_output=True, check=True)
    rendered = json.loads(result.stdout)
    html = rendered['elements']['[data-daily-progression-charts]']['innerHTML']
    assert '4 次成长事件' in html
    assert '新鱼种' in html and '新变异' in html
    assert '标签' in html and '重复' in html
    assert {s['name'] for s in rendered['chart']['series']} == {'新鱼种', '新变异组合', '正常图鉴完成', '新枪获得', '进入新鱼池'}
    tips = '\n'.join(rendered['tips'])
    assert '鱼种 102' in tips and '变异 2' in tips and '新鱼种 / 新变异组合' in tips
    assert '新枪获得' in tips
    assert 'FishRandomPool 2' in tips and '洗脚大盆' in tips
    assert '力量 &gt; 50' in tips and '观察力量 51' in tips

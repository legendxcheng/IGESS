"""First collection facts across formal execution and checkpoint continuation."""
import json
from test_fish_source_joint import archive, initial, project, run


def collection_rows(report):
    return [r for r in report['fish_progression']['persistent']['profiles']['default']['rows']
            if r['source_event_kind'] == 'codex_fish_unlocked']


def test_formal_collection_baseline_and_split_run_preserve_firsts(tmp_path, monkeypatch):
    # Historical fish may have been sold: history, not current inventory, is authoritative.
    initial(monkeypatch, archive("s.collection.unlockedKeys={'101:1','102:2'}"))
    target = project(tmp_path, duration=120, weights={'manual_throw': '1'})
    _, full, full_report = run(target)
    first_output, first, first_report = run(target, until_seconds=45)
    _, second, second_report = run(target, checkpoint_input=first_output / 'final_checkpoint.json')
    scope = full('run_manifest.json')['source_profiles']['default']['collection_growth']
    assert scope['version'] == 1
    assert scope['display_names']['fish']['101'] == '小白条'
    assert {(e['fishId'], e['mutationId']) for e in scope['initial_unlocked_entries']} == {(101, 1), (102, 2)}
    rows = collection_rows(full_report)
    assert rows  # The controlled short run exercises actual source capture, not synthetic events.
    assert not any(r['fish_id'] in {101, 102} and 'new_fish_species' in r['progression_categories'] for r in rows)
    facts = lambda rs: [(r['event_identity'], r['active_time_seconds'], r['progression_categories']) for r in rs]
    assert facts(rows) == facts(collection_rows(first_report) + collection_rows(second_report))
    assert full('timeline.json')[-1] == second('timeline.json')[-1]
    assert full('source_behavior.json')['profiles']['default']['collection_growth'] == scope


def test_hatching_respects_previous_capture_and_waits_for_actual_hatch(tmp_path, monkeypatch):
    state = archive("""
s.collection.unlockedKeys={'101:1'}
s.eggs.items={
 {instanceId=1,eggId=101,rarityId=1,mutationId=1,acquiredAt=0,hatchAt=10,rootSeed=77},
 {instanceId=2,eggId=101,rarityId=1,mutationId=1,acquiredAt=0,hatchAt=20,rootSeed=77},
 {instanceId=3,eggId=102,rarityId=1,mutationId=2,acquiredAt=0,hatchAt=30,rootSeed=77}}
s.eggs.nextInstanceId=4
""")
    initial(monkeypatch, state)
    target = project(tmp_path, duration=35)
    path = target / 'selected/tbfish.json'
    fish = json.loads(path.read_text(encoding='utf-8'))
    for row in fish:
        if row['rarityId'] == 1:
            row['eggWeight'] = 1 if row['id'] == 101 else 0
    path.write_text(json.dumps(fish), encoding='utf-8')
    _, full, full_report = run(target)
    segment, _, before = run(target, until_seconds=25)
    _, restored, after = run(target, checkpoint_input=segment / 'final_checkpoint.json')
    assert collection_rows(before) == []
    rows = collection_rows(full_report)
    assert [(r['fish_id'], r['mutation_id'], r['wall_time_seconds'], r['progression_categories']) for r in rows] == [
        (101, 2, 30, ['new_fish_variant'])]
    assert [r['event_identity'] for r in collection_rows(after)] == [r['event_identity'] for r in rows]
    assert full('timeline.json')[-1] == restored('timeline.json')[-1]
    assert len([e for e in full('events.json') if e['kind'] == 'egg_hatched']) == 3

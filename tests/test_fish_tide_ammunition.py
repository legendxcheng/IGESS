"""Damage/HP drive source reload transactions, including exact rounding."""
import json
import shutil

import pytest

from igess.fish_source_runtime import FishSourceRuntime
from test_fish_source_tides import SOURCE, initial_state


def export(tmp_path, damage, hp):
    data = tmp_path / 'export'
    shutil.copytree(SOURCE / 'igess_export/json', data)
    for name, field, value in [('tbgun.json', 'baseDamage', damage), ('tbegg.json', 'baseHp', hp)]:
        path = data / name
        rows = json.loads(path.read_text(encoding='utf-8'))
        for row in rows:
            row[field] = {'sign': 1, 'digits': str(value), 'scale': 0}
        path.write_text(json.dumps(rows), encoding='utf-8')
    return data


@pytest.mark.parametrize('damage,hp,shots,reloads', [
    (10, 500, 250, 9), (20, 500, 125, 5),
    (100, 500, 25, 1), (10, 60, 30, 1), (10, 61, 35, 2),
    (1000, 1, 5, 1), (10, '60.0000000000000000000000000000001', 35, 2),
])
def test_reload_transactions_follow_damage_and_hp(tmp_path, damage, hp, shots, reloads):
    data = export(tmp_path, damage, hp)
    state = initial_state()
    state['wallet']['material'] = {'sign': 1, 'coeff': '1', 'exp': 6}
    with FishSourceRuntime(SOURCE, data) as runtime:
        runtime.create(start_at=0, initial_state=state, random_seed=37)
        receipt = runtime.request({'op': 'start_tide', 'roundId': 'damage-hp'})
        assert receipt['phase'] == 'participating'
        assert len(receipt['reloads']) == reloads
        assert receipt['ammunition']['shots'] == shots
        assert receipt['ammunition']['magazineSize'] == 30


def test_quote_is_read_only_and_replay_preserves_selected_eggs_and_cost(tmp_path):
    data = export(tmp_path, 10, 61)
    state = initial_state()
    with FishSourceRuntime(SOURCE, data) as original:
        original.create(start_at=0, initial_state=state, random_seed=37)
        before = original.checkpoint()
        quote = original.request({'op': 'query_tide', 'roundId': 'replay'})
        assert original.request({'op': 'query_tide', 'roundId': 'replay'}) == quote
        assert original.checkpoint() == before
        started = original.request({'op': 'start_tide', 'roundId': 'replay'})
        assert started['ammunition'] == quote
        assert started['materialSpent'] == quote['materialCost']
        original.request({'op': 'advance', 'time': 60})
        checkpoint = original.checkpoint()
        original.request({'op': 'advance', 'time': 120})
        complete = original.request({'op': 'complete_tide', 'roundId': 'replay'})
        expected = original.request({'op': 'query'})
    with FishSourceRuntime(SOURCE, data) as restored:
        restored.restore(checkpoint)
        assert restored.request({'op': 'query_tide', 'roundId': 'replay'}) == quote
        assert restored.request({'op': 'start_tide', 'roundId': 'replay'})['materialSpent']['sign'] == 0
        restored.request({'op': 'advance', 'time': 120})
        assert restored.request({'op': 'complete_tide', 'roundId': 'replay'}) == complete
        assert restored.request({'op': 'query'}) == expected
        assert [egg['eggId'] for egg in complete['eggs']] == [egg['eggId'] for egg in quote['eggs']]


def test_budget_uses_the_round_quote_instead_of_six_reloads(tmp_path):
    from igess.fish_source_growth_policy import GrowthTideBudget
    data = export(tmp_path, 100, 500)  # five eggs fit into one paid magazine
    state = initial_state()
    state['wallet']['material'] = {'sign': 1, 'coeff': '12', 'exp': 1}
    with FishSourceRuntime(SOURCE, data) as runtime:
        observed = runtime.create(start_at=0, initial_state=state, random_seed=37)
        quote = runtime.request({'op': 'query_tide', 'roundId': 'budget'})
        observed = runtime.request({'op': 'query'})
        assert GrowthTideBudget().skip(observed, [], {}, lambda *_: True, 0, 7200, tide_quote=quote) is None
        receipt = runtime.request({'op': 'start_tide', 'roundId': 'budget'})
        assert receipt['materialSpent'] == {'sign': 1, 'coeff': '3', 'exp': 1}


def test_permanent_upgrade_changes_attack_and_magazine_count(tmp_path):
    data = export(tmp_path, 10, 500)
    state = initial_state()
    state['combat']['claimedGunRewardIds'] = [102]  # Source +500% permanent bonus.
    with FishSourceRuntime(SOURCE, data) as runtime:
        runtime.create(start_at=0, initial_state=state, random_seed=37)
        quote = runtime.request({'op': 'query_tide', 'roundId': 'upgraded'})
        assert quote['attack'] == {'sign': 1, 'coeff': '6', 'exp': 1}
        assert quote['shots'] == 45 and quote['reloadCount'] == 2
        assert len(runtime.request({'op': 'start_tide', 'roundId': 'upgraded'})['reloads']) == 2


def test_insufficient_material_skips_before_any_payment(tmp_path):
    data = export(tmp_path, 10, 61)
    state = initial_state()
    state['wallet']['material'] = {'sign': 1, 'coeff': '59', 'exp': 0}
    with FishSourceRuntime(SOURCE, data) as runtime:
        runtime.create(start_at=0, initial_state=state)
        receipt = runtime.request({'op': 'start_tide', 'roundId': 'short'})
        assert receipt['reason'] == 'insufficient_material'
        assert receipt['reloads'] == [] and receipt['materialSpent']['sign'] == 0
        assert runtime.request({'op': 'query'})['wallet']['material'] == state['wallet']['material']


def test_formal_admission_and_report_use_damage_quote(tmp_path, monkeypatch):
    from igess.fish_source_growth_policy import GrowthTideBudget
    # This fixture tests source ammunition pricing with a starting wallet.
    monkeypatch.setattr(GrowthTideBudget, 'skip_daily', lambda self, quote: None)
    import yaml
    from pathlib import Path
    from igess.authoring.service import AuthoringService
    from test_fish_source_tides import project
    data = export(tmp_path, 100, 500)
    create = FishSourceRuntime.create
    def fixture(self, **kwargs):
        state = initial_state()
        state['wallet']['material'] = {'sign': 1, 'coeff': '12', 'exp': 1}
        kwargs['initial_state'] = state
        return create(self, **kwargs)
    monkeypatch.setattr(FishSourceRuntime, 'create', fixture)
    target = project(tmp_path, 120)
    path = target / 'economy.yaml'
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    config['engine']['source_runtime']['data_root'] = str(data)
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    response = AuthoringService(target).simulate('smoke')
    assert response.ok, response.details
    output = Path(response.result['output_dir'])
    behavior = json.loads((output / 'source_behavior.json').read_text(encoding='utf-8'))['profiles']['default']
    tide = behavior['tide_rounds'][0]
    assert tide['phase'] == 'completed'
    assert tide['ammunition']['shots'] == 25 and len(tide['reloads']) == 1
    assert tide['totalMaterialSpent'] == {'sign': 1, 'coeff': '3', 'exp': 1}
    report = json.loads((Path(response.result['report_index']).parent / 'report_data.json').read_text(encoding='utf-8'))
    assert report['fish_progression']['actions']['default']['tide_rounds'] == behavior['tide_rounds']

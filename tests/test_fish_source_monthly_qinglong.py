"""Monthly card + on-sale privileges + 29 Qinglong, without a paid gun."""
import json
from pathlib import Path

import pytest

from igess.authoring.service import AuthoringService
from igess.fish_source_engine import _unpack_session
from igess.fish_source_runtime import FishSourceRuntime
from test_fish_source_formal import FISH_SOURCE, _project

pytestmark = pytest.mark.skipif(
    not (FISH_SOURCE / 'simulation/cli.lua').exists(), reason='paired Fish checkout required',
)


def test_monthly_qinglong_inventory_benefits_and_process_restore():
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / 'igess_export/json') as runtime:
        state = runtime.create(start_at=0, initial_loadout_mode='qinglong_29',
                               monthly_card_mode='monthly_once', permanent_privilege_mode='all_on_sale')
        assert len(state['inventory']['items']) == 29
        assert all(f['fishId'] == 2004 for f in state['inventory']['items'])
        assert state['guns']['combat']['ownedGunIds'] == []
        assert state['guns']['combat']['equippedGunId'] == 0
        loadout = runtime.request({'op': 'query_initial_loadout'})
        assert loadout['fishCount'] == 29 and loadout['gunCount'] == 0
        assert 'gunId' not in loadout
        privileges = runtime.request({'op': 'query_permanent_privileges'})
        assert privileges['mode'] == 'all_on_sale' and privileges['items']
        assert runtime.request({'op': 'claim_monthly_card'})['success']
        card = runtime.request({'op': 'query_monthly_card'})
        assert card['nativeInventory'] == [{'itemId': 8310011, 'count': 4}]
        checkpoint = runtime.checkpoint()
        expected = runtime.request({'op': 'query'})
    with FishSourceRuntime(FISH_SOURCE, FISH_SOURCE / 'igess_export/json') as restored:
        assert restored.restore(checkpoint) == expected
        assert restored.request({'op': 'query_initial_loadout'}) == loadout
        assert restored.request({'op': 'query_monthly_card'}) == card


def test_monthly_qinglong_formal_smoke_and_cross_loadout_rejection(tmp_path):
    project = _project(tmp_path)
    service = AuthoringService(project)
    result = service.simulate('smoke_monthly_qinglong_29')
    assert result.ok, result
    output = Path(result.result['output_dir'])
    manifest = json.loads((output / 'run_manifest.json').read_text('utf-8'))
    profile = manifest['source_profiles']['default']
    assert profile['initial_loadout']['mode'] == 'qinglong_29'
    assert profile['initial_loadout']['fishCount'] == 29
    assert profile['initial_loadout']['gunCount'] == 0
    assert profile['permanent_privileges']['mode'] == 'all_on_sale'
    assert profile['monthly_card_final']['nativeInventory'] == [{'itemId': 8310011, 'count': 4}]
    assert profile['collection_growth']['initial_gun_facts'] == []
    behavior = json.loads((output / 'source_behavior.json').read_text('utf-8'))['profiles']['default']
    assert behavior['rejected_commands'] == {}
    assert Path(result.result['report_index']).exists()
    cp = json.loads((output / 'final_checkpoint.json').read_text('utf-8'))
    assert cp['simulated_time_seconds'] == 600
    with FishSourceRuntime(FISH_SOURCE, project / 'production_snapshot/json') as restored:
        state = restored.restore(_unpack_session(cp['engine_state']))
        assert state['guns']['combat']['ownedGunIds'] == []
    mismatch = service.simulate('month_1_monthly_all_permanent',
                               checkpoint_input=output / 'final_checkpoint.json', until_seconds=601)
    assert not mismatch.ok and 'checkpoint_loadout_mismatch' in str(mismatch)

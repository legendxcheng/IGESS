"""Purchased-beast player decisions; rates and transactions stay source-owned."""
from .fish_source_numbers import source_decimal


def choose_loadout_hall_action(state, actions, allowed):
    items = state['inventory']['items']
    normal = [row for row in actions['hallCandidates'] if not row['isBeast']]
    if not normal:
        return None  # Reserve slot 1 until the player actually catches a fish.
    best = max(normal, key=lambda row: (source_decimal(row['currentRate']), -row['instanceId']))
    occupied = {row['hallSlot']: row for row in items if row.get('hallSlot', 0) > 0}
    if occupied.get(1, {}).get('instanceId') != best['instanceId']:
        if 1 in occupied:
            old = occupied[1]['instanceId']
            if allowed('withdraw_fish', str(old)):
                return 'withdraw_fish', str(old), {'op': 'withdraw_fish', 'instanceId': old}
        elif allowed('deploy_fish', str(best['instanceId'])):
            return 'deploy_fish', str(best['instanceId']), {
                'op': 'deploy_fish', 'instanceId': best['instanceId'], 'slot': 1,
            }
        return None
    beasts = {row['instanceId'] for row in actions['hallCandidates'] if row['isBeast']}
    for item in sorted(items, key=lambda row: row['instanceId']):
        if item['instanceId'] not in beasts or item.get('hallSlot', 0) > 0:
            continue
        for slot in range(2, state['hall']['currentLevel']['capacity'] + 1):
            if slot not in occupied and allowed('deploy_fish', str(item['instanceId'])):
                return 'deploy_fish', str(item['instanceId']), {
                    'op': 'deploy_fish', 'instanceId': item['instanceId'], 'slot': slot,
                }
    return None

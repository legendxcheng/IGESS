"""Player decisions and permanent observations for source-owned gun progression."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .schema import Event


def _number(dto: dict[str, Any]) -> Decimal:
    if dto['sign'] == 0:
        return Decimal(0)
    digits = Decimal(dto['coeff']).as_tuple().digits
    return Decimal((int(dto['sign'] < 0), digits, dto['exp']))


def choose_gun_action(state: dict[str, Any], allowed: Any):
    guns = state['guns']
    for reward in sorted(guns['rewards'], key=lambda row: row['id']):
        identity = str(reward['id'])
        if (reward['rewardType'] == 'gun_unlock' and reward['eligible']
                and not reward['claimed'] and allowed('claim_gun_reward', identity)):
            return 'claim_gun_reward', identity, {'op': 'claim_gun_reward', 'rewardId': reward['id']}
    owned = sorted(guns['owned'], key=lambda row: row['id'])
    if owned:
        best = max(owned, key=lambda row: _number(row['attack']))['id']
        if best != guns['combat']['equippedGunId'] and allowed('equip_gun', str(best)):
            return 'equip_gun', str(best), {'op': 'equip_gun', 'gunId': best}
    return None


class GunMilestones:
    def __init__(self, saved: dict[str, Any] | None = None):
        self.seen = set((saved or {}).get('seen', []))

    def save(self) -> dict[str, Any]:
        return {'seen': sorted(self.seen)}

    def observe(self, state, online_seconds, scenario_id, profile_id, events):
        guns = state['guns']
        facts = []
        for reward in guns['rewards']:
            if reward['rewardType'] == 'gun_unlock':
                if reward['eligible']:
                    facts.append(('normal_codex_completed', str(reward['id'])))
                if reward['claimed']:
                    facts.append(('gun_claimed', str(reward['id'])))
            elif reward['claimed']:
                facts.append(('gun_upgraded', str(reward['id'])))
        for gun in guns['owned']:
            facts.append(('gun_owned', str(gun['id'])))
        if guns['combat']['equippedGunId']:
            facts.append(('gun_equipped', str(guns['combat']['equippedGunId'])))
        if guns['tideEligible']:
            facts.append(('fish_tide_unlocked', 'any_owned_gun'))
        for kind, target in facts:
            identity = f'{kind}:{target}'
            if identity in self.seen:
                continue
            self.seen.add(identity)
            events.append(Event(scenario_id, profile_id, int(state['time']), 'gun_milestone', target, {
                'kind': kind, 'identity': identity, 'online_time_seconds': str(online_seconds),
            }))

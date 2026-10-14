"""Observed egg admission/hatch facts; never an automatic reward policy."""
from __future__ import annotations

from .schema import Event


class EggObservations:
    def __init__(self, saved=None):
        self.seen = set((saved or {}).get('seen', []))

    def save(self):
        return {'seen': sorted(self.seen)}

    def observe(self, state, online_seconds, scenario_id, profile_id, events):
        eggs = state['eggs']
        facts = []
        for grant in eggs['grants']:
            receipt = grant['receipt']
            for instance_id in receipt['instanceIds']:
                facts.append(('egg_admitted', instance_id, receipt.get('acquiredAt', state['time']), {
                    'egg_id': str(grant['eggId']), 'request_id': grant['requestId'],
                    'hatch_at': str(receipt.get('hatchAt', '')),
                }))
        for hatch in eggs['hatched']:
            fish = hatch['fish']
            facts.append(('egg_hatched', hatch['eggInstanceId'], hatch['time'], {
                'egg_id': str(hatch['eggId']), 'fish_instance_id': str(fish['instanceId']),
                'fish_id': str(fish['fishId']), 'mutation_id': str(fish['mutationId']),
            }))
        for kind, instance_id, time, details in facts:
            identity = f'{kind}:{instance_id}'
            if identity in self.seen:
                continue
            self.seen.add(identity)
            elapsed = max(0, state['time'] - time) if state['online'] else 0
            events.append(Event(scenario_id, profile_id, int(time), kind, str(instance_id), {
                **details, 'identity': identity,
                'online_time_seconds': str(max(0, online_seconds - elapsed)),
            }))

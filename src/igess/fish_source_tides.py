"""Receipt observations for fixed-successful-egg fish tide participation."""
import json
from .schema import Event

TIDE_POLICY = {'model': 'fixed_successful_eggs_v1', 'eggs': 5, 'duration_seconds': 120, 'reloads': 6,
               'competition': 'not_simulated', 'gun_damage_affects_yield': False}

class TideObservations:
    def __init__(self, saved=None):
        self.seen = dict((saved or {}).get("seen", {}))
        self.starts = dict((saved or {}).get("starts", {}))

    def save(self):
        return {"seen": dict(self.seen), "starts": dict(self.starts)}

    def observe(self, state, online_seconds, scenario_id, profile_id, events):
        for source in state['tides']['rounds']:
            row = dict(source)
            row['occupied_seconds'] = min(120, max(0, state['time'] - row['openedAt'])) if row['phase'] != 'skipped' else 0
            self.starts.setdefault(row['roundId'], max(0, online_seconds - row['occupied_seconds']))
            row['online_time_seconds'] = self.starts[row['roundId']] + row['occupied_seconds']
            row['approximation'] = TIDE_POLICY['model']
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if self.seen.get(row['roundId']) == encoded:
                continue
            self.seen[row['roundId']] = encoded
            events.append(Event(scenario_id, profile_id, int(state['time']), 'tide_observed', row['roundId'],
                                {'receipt': encoded, 'source': 'observation'}))

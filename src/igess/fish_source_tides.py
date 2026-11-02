"""Receipt observations for fixed-successful-egg fish tide participation."""
import json
from .schema import Event

TIDE_POLICY = {
    "model": "fixed_eggs_damage_hp_ammunition_v2", "eggs": 5, "duration_seconds": 120,
    "magazine_size": 30, "initial_ammo": 0, "competition": "not_simulated",
    "gun_damage_affects_yield": False, "gun_damage_affects_reload_count": True,
    "shot_policy": "sum_per_egg_ceiling_hp_over_attack_perfect_hits",
    "leftover_ammo": "discarded_after_round",
}


class TideObservations:
    def __init__(self, saved=None):
        self.seen = dict((saved or {}).get("seen", {}))
        self.starts = dict((saved or {}).get("starts", {}))
        self.receipts = dict((saved or {}).get("receipts", {}))

    def save(self):
        return {"seen": dict(self.seen), "starts": dict(self.starts), "receipts": dict(self.receipts)}

    def observe(self, state, online_seconds, scenario_id, profile_id, events, *, final=False):
        for source in state["tides"]["rounds"]:
            identity = source["roundId"]
            # Sampling observes a running round; it is not a new business transition.
            source_key = json.dumps(source, ensure_ascii=False, sort_keys=True)
            changed = self.seen.get(identity) != source_key
            if not changed and not final:
                continue
            # Query projects only the current/latest source round. Earlier
            # rounds already live in events, so the checkpoint needs one cursor.
            self.seen = {identity: source_key}
            self.starts = {identity: self.starts[identity]} if identity in self.starts else {}
            self.receipts = {identity: self.receipts[identity]} if identity in self.receipts else {}
            row = dict(source)
            row["occupied_seconds"] = (
                min(120, max(0, state["time"] - row["openedAt"]))
                if row["phase"] != "skipped" else 0
            )
            self.starts.setdefault(identity, max(0, online_seconds - row["occupied_seconds"]))
            row["online_time_seconds"] = self.starts[identity] + row["occupied_seconds"]
            row["approximation"] = TIDE_POLICY["model"]
            encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if self.receipts.get(identity) == encoded:
                continue
            self.receipts[identity] = encoded
            events.append(Event(
                scenario_id, profile_id, int(state["time"]), "tide_observed", identity,
                {"receipt": encoded, "source": "observation"},
            ))


def tide_report_rows(rounds, egg_events):
    """Attach admission totals and observed hatches by stable egg instance identity."""
    hatched = {event["identity"].split(":", 1)[1] for event in egg_events
               if event["kind"] == "egg_hatched"}
    rows = []
    for source in rounds:
        row = dict(source)
        admitted = {str(identity) for egg in row.get("eggs", []) if egg.get("admitted")
                    for identity in egg.get("instanceIds", [])}
        row["admitted_egg_count"] = len(admitted)
        row["hatched_egg_count"] = len(admitted & hatched)
        rows.append(row)
    return sorted(rows, key=lambda row: row["openedAt"])

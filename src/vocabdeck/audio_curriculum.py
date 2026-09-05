"""Audio-aware candidate state; rejects/repairs happen before reservations."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .semantic_benchmark import digest
from .validation import _learning_unit_key, merge_validation_reports


def media_identity(card):
    path = Path(str(card.get("video_path") or "")).expanduser()
    if not path.is_file():
        return None
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class AudioCurriculumSession:
    def __init__(self, cards, gate, cache_directory, *, state=None, validation=None):
        self.source_hash = digest(cards)
        self.gate = gate
        self.cache_directory = Path(cache_directory)
        self.original = {int(c["audit_position"]): deepcopy(c) for c in cards}
        if len(self.original) != len(cards):
            raise ValueError("audio curriculum requires unique audit positions")
        self.cards = deepcopy(self.original)
        self.records = {}
        from .audio_validation import CTC_BACKEND_VERSION
        config = getattr(gate, "config", None)
        self.gate_hash = digest({"backend_version": CTC_BACKEND_VERSION,
                                 "config": asdict(config) if is_dataclass(config) else None,
                                 "resource_policy": getattr(gate, "resource_policy", None)})
        if state is None and (validation or {}).get("audio_required"):
            raise ValueError("missing audio state for resumed audio-validated run")
        if state is not None:
            if state.get("source_hash") != self.source_hash or state.get("version") != 1:
                raise ValueError("audio resume source fingerprint mismatch")
            if state.get("gate_hash") != self.gate_hash:
                raise ValueError("audio resume gate configuration mismatch")
            if state.get("validation_hash") != digest(validation):
                raise ValueError("audio resume validation fingerprint mismatch; checkpoint files are not a matched set")
            if state.get("records_hash") != digest(state["records"]):
                raise ValueError("audio resume record fingerprint mismatch")
            for record in state["records"]:
                position = int(record["audit_position"])
                if position not in self.cards or position in self.records:
                    raise ValueError("invalid audio resume position")
                if record.get("media_identity") != media_identity(self.original[position]):
                    raise ValueError("audio resume media changed; rebuild audio evidence")
                self.records[position] = deepcopy(record)
                if record["status"] == "accepted":
                    self.cards[position] = deepcopy(record["card"])
        self.regroup()

    def regroup(self):
        """Reading repairs may split or join exact units; don't mix them in a group."""
        if not any(r.get("repaired") for r in self.records.values()):
            return
        ranks = {}
        for position, c in self.cards.items():
            rank = int(self.original[position].get("curriculum_position") or position)
            unit = _learning_unit_key(c)
            ranks[unit] = min(ranks.get(unit, rank), rank)
        positions = {u: i for i, u in enumerate(sorted(ranks, key=lambda u: (ranks[u], u)), 1)}
        for c in self.cards.values():
            c["curriculum_position"] = positions[_learning_unit_key(c)]

    def check(self, position):
        if position in self.records:
            return self.records[position]
        current = self.cards[position]
        result = self.gate.review(current, self.cache_directory)
        if result.get("status") not in {"accepted", "rejected"}:
            raise ValueError("audio backend returned invalid status")
        record = {"audit_position": position, "status": result["status"],
                  "reason": result.get("reason"), "source_card_hash": digest(self.original[position]),
                  "media_identity": media_identity(self.original[position]),
                  "resource_policy": getattr(self.gate, "resource_policy", None)}
        if result["status"] == "accepted":
            c = deepcopy(result["card"])
            if int(c.get("audit_position", -1)) != position or c.get("audio_validation", {}).get("status") != "accepted":
                raise ValueError("accepted audio result missing matching card evidence")
            record.update(card=c, repaired=bool(c.get("requires_contextual_revalidation")))
            self.cards[position] = c
        else:
            record["attempts"] = result.get("attempts", [])
        self.records[position] = record
        self.regroup()
        return record

    @staticmethod
    def rejected(position, reason):
        return {"audit_position": position, "decision": {
            "status": "rejected", "failed_stage": "audio_content",
            "reason_codes": [f"audio:{reason}"], "stages": []}}

    def gate_resumed_validation(self, validation):
        result = deepcopy(validation)
        result["audio_required"] = True
        keep, failures = [], []
        for row in result.get("accepted", []):
            position = int(row["audit_position"])
            record = self.check(position)
            if record["status"] != "accepted":
                failures.append(self.rejected(position, record["reason"]))
            elif self.cards[position].get("requires_contextual_revalidation"):
                # Remove the old semantic verdict: the repaired candidate must
                # reenter the constrained review frontier with its new identity.
                continue
            else:
                row["decision"]["audio_content"] = self.cards[position]["audio_validation"]
                keep.append(row)
        result["accepted"] = keep
        return merge_validation_reports(result, {"rejected": failures})

    def gate_frontier(self, frontier, validation):
        accepted, failures = [], []
        for c in frontier:
            position = int(c["audit_position"])
            record = self.check(position)
            if record["status"] == "accepted":
                accepted.append(position)
            else:
                failures.append(self.rejected(position, record["reason"]))
        return [self.cards[p] for p in accepted], merge_validation_reports(validation, {"rejected": failures})

    def attach_semantic_results(self, report):
        for row in report.get("accepted", []):
            position = int(row["audit_position"])
            c = self.cards[position]
            if position not in self.records or self.records[position]["status"] != "accepted":
                raise ValueError("semantic acceptance without audio evidence")
            c.pop("requires_contextual_revalidation", None)
            row["decision"]["audio_content"] = c["audio_validation"]
            # Persist the cleared pending flag only after fresh semantic success.
            self.records[position]["card"] = deepcopy(c)
        return report

    def snapshot(self, validation):
        records = [self.records[p] for p in sorted(self.records)]
        return {"version": 1, "source_hash": self.source_hash, "validation_hash": digest(validation),
                "gate_hash": self.gate_hash,
                "records": records, "records_hash": digest(records),
                "summary": {"checked": len(records),
                            "accepted_audio": sum(r["status"] == "accepted" for r in records),
                            "repaired": sum(bool(r.get("repaired")) for r in records)}}

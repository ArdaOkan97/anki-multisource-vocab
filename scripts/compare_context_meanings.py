"""Read-only paired comparison at the existing deck order; no model inference."""
import argparse
import json
from pathlib import Path

from vocabdeck.database import VocabularyDatabase
from vocabdeck.context_meanings import context_meaning_issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {args.db.resolve(), args.selection.resolve()}:
        parser.error("output cannot overwrite input")
    db = VocabularyDatabase(args.db, read_only=True)
    cards = json.loads(args.selection.read_text())["accepted"]
    known, changes = set(), []
    try:
        for position, original in enumerate(cards, 1):
            card = dict(original)
            deps = db.sentence_meaning_dependencies(card["sentence_id"])
            card.update(context_meanings_version=1, context_meaning_dependencies=deps,
                        context_learning_unit_keys=sorted({d["learning_unit_key"] for d in deps}))
            previous = set(original["context_learning_unit_keys"])
            current = set(card["context_learning_unit_keys"])
            initial = set(card.get("initial_known_context_learning_unit_keys") or [])
            target = card["learning_unit_key"]
            issues = context_meaning_issues(card)
            if previous != current or issues:
                changes.append(dict(position=position, lemma=card["lemma"], japanese=card["japanese"],
                                    before_unknown=len(previous - known - initial - {target}),
                                    after_unknown=len(current - known - initial - {target}),
                                    issues=issues, dependencies=deps))
            known.add(target)
    finally:
        db.close()
    result = dict(cards=len(cards), changed_cards=len(changes), changes=changes,
                  interpretation="Paired fixed-order comparison, holding prior learning constant; not a regenerated curriculum or accuracy estimate.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "changes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

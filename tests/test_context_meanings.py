import pytest

from vocabdeck.context_meanings import resolve_dependency_spans, context_meaning_issues
from vocabdeck.database import VocabularyDatabase
from vocabdeck.tokenizer import JapaneseTokenizer
from vocabdeck.subtitles import Cue
from test_global_deduplication import FixedExpressionScorer
from test_candidate_accounting import candidate, validation
from vocabdeck.validation import DeterministicCardValidator, select_validated_curriculum


def dep(key, start, end, resolution="occurrence_sense"):
    return dict(learning_unit_key=key, start=start, end=end, resolution=resolution)


def analysis(start, end, decision="ambiguous"):
    return dict(start_char=start, end_char=end, decision=decision)


@pytest.mark.parametrize("decision", ["ambiguous", "insufficient_evidence", "not_analyzed"])
def test_uncertain_phrase_cannot_inherit_component_mastery(decision):
    resolved = resolve_dependency_spans(
        "何でそう思う", "Why think that?", [dep("what", 0, 1), dep("so", 2, 4), dep("think", 4, 6)],
        [analysis(0, 2, decision)],
    )
    assert len(resolved) == 3
    assert resolved[0]["surface"] == "何で"
    assert resolved[0]["learning_unit_key"].startswith("unresolved-context:")
    assert "what" not in {d["learning_unit_key"] for d in resolved}


def test_resolved_components_and_nested_expression_are_preserved():
    components = [dep("good", 0, 2), dep("face", 2, 3)]
    assert resolve_dependency_spans("いい顔", "nice face", components, [analysis(0, 3, "components")]) == components
    expression = [dep("thanks", 0, 3, "expression")]
    assert resolve_dependency_spans("どうも", "Thanks", expression, [analysis(0, 2)]) == expression


def test_overlapping_uncertainty_counts_once_and_is_occurrence_specific():
    deps = [dep("a", 0, 2), dep("b", 2, 4)]
    resolved = resolve_dependency_spans("あいうえ", "context", deps, [analysis(0, 3), analysis(2, 4)])
    assert len(resolved) == 1
    assert resolved[0]["surface"] == "あいうえ"
    other = resolve_dependency_spans("あいうえ", "other context", deps, [analysis(0, 4)])
    assert other[0]["learning_unit_key"] != resolved[0]["learning_unit_key"]


@pytest.mark.parametrize("decision", ["expression", "components", "ambiguous"])
def test_database_dependency_accounting_uses_expression_decisions(tmp_path, decision):
    db = VocabularyDatabase(tmp_path / "test.sqlite")
    db.initialize()
    source = db.add_source(series="Test", season=1, episode=1, title=None,
                           video_path=None, japanese_subtitle_path="test.srt", english_subtitle_path=None)
    db.ingest_cues(source, [Cue(1, 0, 1000, "何で そう思う？")],
                   [Cue(1, 0, 1000, "Why do you think that?")],
                   JapaneseTokenizer(expression_scorer=FixedExpressionScorer(decision)))
    sentence = db.connection.execute("SELECT id FROM sentences").fetchone()[0]
    dependencies = db.sentence_meaning_dependencies(sentence)
    assert db.sentence_learning_unit_keys(sentence) == {d["learning_unit_key"] for d in dependencies}
    first = dependencies[0]
    assert first["resolution"] == {
        "expression": "expression", "components": "occurrence_sense",
        "ambiguous": "unresolved_expression",
    }[decision]
    assert first["end"] == (1 if decision == "components" else 2)
    # Cache results must not be externally mutable.
    dependencies[0]["learning_unit_key"] = "corrupt"
    assert "corrupt" not in db.sentence_learning_unit_keys(sentence)
    db.close()


def test_target_and_context_guards_reject_stale_accepted_decisions():
    card = candidate(1, "eat")
    card["japanese"] = "食べる。何で"
    card.update(context_meanings_version=1,
                context_meaning_dependencies=[dep("eat", 0, 3), dep("unresolved-context:x", 4, 6, "unresolved_expression")],
                context_learning_unit_keys=["eat", "unresolved-context:x"])
    assert context_meaning_issues(card) == ["unresolved_context_expression"]
    assert DeterministicCardValidator().validate(card).status == "rejected"
    selected = select_validated_curriculum([card], validation((card, "accepted")), harder_unknown_tolerance=None)
    assert selected["accepted"] == []
    card["context_meaning_dependencies"] = [dep("another-sense", 0, 3)]
    card["context_learning_unit_keys"] = ["another-sense"]
    assert "target_context_meaning_mismatch" in context_meaning_issues(card)


def test_legacy_import_without_expression_analysis_is_not_assumed_resolved(tmp_path):
    db = VocabularyDatabase(tmp_path / "legacy.sqlite")
    db.initialize()
    source = db.add_source(series="Legacy", season=1, episode=1, title=None,
                           video_path=None, japanese_subtitle_path="a.srt", english_subtitle_path=None)
    db.ingest_cues(source, [Cue(1, 0, 1000, "何で？")], [Cue(1, 0, 1000, "Why?")], JapaneseTokenizer())
    sentence = db.connection.execute("SELECT id FROM sentences").fetchone()[0]
    deps = db.sentence_meaning_dependencies(sentence)
    assert deps[0]["resolution"] == "unresolved_expression"
    assert deps[0]["expression_evidence"][0]["decision"] == "not_analyzed"
    db.close()
    import sqlite3
    readonly = VocabularyDatabase(tmp_path / "legacy.sqlite", read_only=True)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.connection.execute("DELETE FROM sentences")
    readonly.close()


def test_malformed_context_metadata_fails_closed():
    card = candidate(1, "eat")
    card.update(context_meanings_version=1, context_meaning_dependencies=[{}])
    assert context_meaning_issues(card) == ["invalid_context_meaning_metadata"]

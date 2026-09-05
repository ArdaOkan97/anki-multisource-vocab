import pytest

from vocabdeck.embedding_pair_probe import MODELS, cosine, make_pairs, run


def test_cosine_identity_symmetry_and_opposites():
    a, b = [1., 2., 3.], [4., 1., 2.]
    assert cosine(a, a) == pytest.approx(1)
    assert cosine(a, b) == cosine(b, a)
    assert cosine(a, [-x for x in a]) == pytest.approx(-1)
    assert cosine([1., 0.], [0., 1.]) == pytest.approx(0)


@pytest.mark.parametrize("left,right", [([], []), ([0], [0]), ([1], [1, 2]),
                                         ([float('nan')], [1]), ([float('inf')], [1])])
def test_invalid_vectors_fail_closed(left, right):
    with pytest.raises(ValueError):
        cosine(left, right)


def test_added_examples_explicitly_provisional():
    pairs = make_pairs({"schema_version": 1, "cases": []})
    assert len(pairs) == 12
    assert all(p["kind"] == "assistant_diagnostic" and p["gold"] is None for p in pairs)
    assert len({p["case_id"] for p in pairs}) == len(pairs)
    assert {p["provisional_category"] for p in pairs} == {"paraphrase", "related_distinct", "unrelated"}


def test_model_pinning_and_symmetric_prefix():
    assert MODELS["e5"][2] == "query: "
    assert all(len(config[1]) == 40 for config in MODELS.values())
    assert all(MODELS[key][2] == "" for key in ("mpnet", "bge-base", "bge-large"))


def test_rss_budget_cannot_be_raised():
    with pytest.raises(ValueError, match="RSS ceiling"):
        run("e5", {}, "unused", rss_limit_gib=5)

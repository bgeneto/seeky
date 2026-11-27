# WP-0.6: deterministic public-sample selection and malformed-input checks.
import pytest

from seeky_model_export.data import (
    DataError,
    DeterministicReservoir,
    parse_qrels,
    parse_tsv_row,
    strip_gutenberg,
)


def test_reservoir_is_deterministic_under_input_permutation():
    rows = [{"id": str(number), "text": f"passage {number}"} for number in range(30)]
    forward = DeterministicReservoir(5, "fixed-seed")
    reverse = DeterministicReservoir(5, "fixed-seed")
    for row in rows:
        forward.add(row)
    for row in reversed(rows):
        reverse.add(row)
    assert forward.values() == reverse.values()
    assert len(forward.values()) == 5


def test_reservoir_excludes_exact_duplicate_text():
    reservoir = DeterministicReservoir(2, "fixed-seed")
    reservoir.add({"id": "a", "text": "same"})
    reservoir.add({"id": "b", "text": "same"})
    reservoir.add({"id": "c", "text": "different"})
    values = reservoir.values()
    assert len(values) == 2
    assert len({row["text"] for row in values}) == 2


def test_tsv_row_rejects_malformed_external_input_without_echoing_text():
    assert parse_tsv_row("identifier\tcontents") == ["identifier", "contents"]
    with pytest.raises(DataError) as error:
        parse_tsv_row("private text without a tab", columns=2)
    assert "private text" not in str(error.value)


def test_qrels_parser_accepts_trec_and_two_column_forms():
    assert parse_qrels("q1 0 d1 2\nq2\td2\t1\n") == {
        "q1": {"d1": 2},
        "q2": {"d2": 1},
    }
    with pytest.raises(DataError):
        parse_qrels("q1 0 d1 not-a-number\n")


def test_gutenberg_markers_remove_license_and_keep_body():
    text = (
        "license header\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK EXAMPLE ***\n"
        "Chapter I\nPublic-domain body.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK EXAMPLE ***\n"
        "license footer\n"
    )
    assert strip_gutenberg(text) == "Chapter I\nPublic-domain body."
    with pytest.raises(DataError):
        strip_gutenberg("no markers and potentially the wrong book")

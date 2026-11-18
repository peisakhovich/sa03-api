"""Tests for server-side voice-token comparison."""

from voice_assessment import compare_voice_text


def _types(result):
    return [item["type"] for item in result["alignment"]]


def test_exact_phrase():
    result = compare_voice_text(
        "Dzień dobry, kupię chleb.",
        ["Dzień", "dobry", "kupię", "chleb"],
    )

    assert result["success"] is True
    assert result["edit_distance"] == 0
    assert result["counts"] == {
        "matches": 4,
        "substitutions": 0,
        "omissions": 0,
        "insertions": 0,
    }
    assert _types(result) == ["match"] * 4


def test_extra_word_is_insertion_and_later_words_stay_aligned():
    result = compare_voice_text(
        "Dzień dobry kupię chleb",
        ["Dzień", "dobry", "naprawdę", "kupię", "chleb"],
    )

    assert result["counts"] == {
        "matches": 4,
        "substitutions": 0,
        "omissions": 0,
        "insertions": 1,
    }
    assert result["alignment"][2] == {
        "type": "insertion",
        "reference_word": None,
        "recognized_word": "naprawdę",
    }


def test_omission():
    result = compare_voice_text(
        "Ja bardzo lubię kawę",
        ["Ja", "lubię", "kawę"],
    )

    assert result["counts"]["omissions"] == 1
    assert result["alignment"][1] == {
        "type": "omission",
        "reference_word": "bardzo",
        "recognized_word": None,
    }


def test_substitution():
    result = compare_voice_text(
        "Ja lubię kawę",
        ["Ja", "kocham", "kawę"],
    )

    assert result["counts"]["substitutions"] == 1
    assert result["alignment"][1] == {
        "type": "substitution",
        "reference_word": "lubię",
        "recognized_word": "kocham",
    }


def test_edge_punctuation_is_ignored_for_matching():
    result = compare_voice_text(
        "Dzień dobry, jak się masz?",
        ["Dzień", "dobry", "jak", "się", "masz"],
    )

    assert result["edit_distance"] == 0
    assert result["counts"]["matches"] == 5


def test_repeated_words_preserve_token_occurrences():
    result = compare_voice_text(
        "Ja bardzo bardzo lubię kawę",
        ["Ja", "bardzo", "lubię", "kawę"],
    )

    assert result["counts"]["matches"] == 4
    assert result["counts"]["omissions"] == 1
    assert sum(item["reference_word"] is not None for item in result["alignment"]) == 5
    assert sum(item["recognized_word"] is not None for item in result["alignment"]) == 4


def test_azure_reference_tokens_are_used_when_token_count_matches():
    result = compare_voice_text(
        "Kupię 7 jabłek",
        ["Kupię", "siedem", "jabłek"],
        azure_reference_words=["Kupię", "siedem", "jabłek"],
    )

    assert result["edit_distance"] == 0
    assert result["alignment"][1]["reference_word"] == "siedem"


def test_empty_transcript_marks_all_reference_words_as_omissions():
    result = compare_voice_text("Ja lubię kawę", [])

    assert result["counts"]["omissions"] == 3
    assert result["counts"]["matches"] == 0
    assert result["edit_distance"] == 3

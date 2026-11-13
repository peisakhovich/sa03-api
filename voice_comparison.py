"""Deterministic word-level comparison of a reference and an STT transcript."""

import re
import unicodedata


_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)


def _tokens(text: str) -> list[str]:
    """Return lowercase word tokens without surrounding punctuation."""
    if not isinstance(text, str):
        return []
    return [
        unicodedata.normalize("NFC", match.group(0)).casefold()
        for match in _TOKEN_RE.finditer(text)
    ]


def compare_transcription(reference_text: str, recognition: dict) -> dict:
    """Align recognized words with reference words using word-level Levenshtein.

    Exact matches cost 0; substitutions, insertions and omissions cost 1.
    Recognition confidence and timing are retained for the recognized token.
    """
    reference = _tokens(reference_text)
    raw_words = recognition.get("words") if isinstance(recognition, dict) else None

    recognized = []
    if isinstance(raw_words, list) and raw_words:
        for item in raw_words:
            if not isinstance(item, dict):
                continue
            token_list = _tokens(item.get("word", ""))
            for token in token_list:
                recognized.append({
                    "token": token,
                    "word": item.get("word", token),
                    "confidence": item.get("confidence"),
                    "offset_ms": item.get("offset_ms"),
                    "duration_ms": item.get("duration_ms"),
                })
    else:
        recognized = [
            {
                "token": token,
                "word": token,
                "confidence": None,
                "offset_ms": None,
                "duration_ms": None,
            }
            for token in _tokens(recognition.get("recognized_text", ""))
        ]

    hypothesis = [item["token"] for item in recognized]
    rows, cols = len(reference), len(hypothesis)

    # Dynamic programming matrix: minimum edit cost for each prefix pair.
    dp = [[0] * (cols + 1) for _ in range(rows + 1)]
    back = [[None] * (cols + 1) for _ in range(rows + 1)]

    for i in range(1, rows + 1):
        dp[i][0] = i
        back[i][0] = "omission"
    for j in range(1, cols + 1):
        dp[0][j] = j
        back[0][j] = "insertion"

    for i in range(1, rows + 1):
        for j in range(1, cols + 1):
            if reference[i - 1] == hypothesis[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
                back[i][j] = "match"
                continue

            # Prefer substitution on equal-cost ties, then omission, then insertion.
            choices = (
                (dp[i - 1][j - 1] + 1, "substitution"),
                (dp[i - 1][j] + 1, "omission"),
                (dp[i][j - 1] + 1, "insertion"),
            )
            dp[i][j], back[i][j] = min(choices, key=lambda item: item[0])

    aligned = []
    i, j = rows, cols
    while i > 0 or j > 0:
        operation = back[i][j]
        if operation in ("match", "substitution"):
            ref_word = reference[i - 1]
            heard = recognized[j - 1]
            aligned.append({
                "type": operation,
                "reference_word": ref_word,
                "recognized_word": heard["word"],
                "confidence": heard["confidence"],
                "offset_ms": heard["offset_ms"],
                "duration_ms": heard["duration_ms"],
            })
            i -= 1
            j -= 1
        elif operation == "omission":
            aligned.append({
                "type": "omission",
                "reference_word": reference[i - 1],
                "recognized_word": None,
                "confidence": None,
                "offset_ms": None,
                "duration_ms": None,
            })
            i -= 1
        elif operation == "insertion":
            heard = recognized[j - 1]
            aligned.append({
                "type": "insertion",
                "reference_word": None,
                "recognized_word": heard["word"],
                "confidence": heard["confidence"],
                "offset_ms": heard["offset_ms"],
                "duration_ms": heard["duration_ms"],
            })
            j -= 1

    aligned.reverse()
    counts = {
        "matches": sum(item["type"] == "match" for item in aligned),
        "substitutions": sum(item["type"] == "substitution" for item in aligned),
        "omissions": sum(item["type"] == "omission" for item in aligned),
        "insertions": sum(item["type"] == "insertion" for item in aligned),
    }

    return {
        "method": "word_level_levenshtein",
        "reference_word_count": rows,
        "recognized_word_count": cols,
        "edit_distance": dp[rows][cols],
        "counts": counts,
        "items": [item for item in aligned if item["type"] != "match"],
        "alignment": aligned,
    }

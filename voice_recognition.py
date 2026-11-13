"""Azure Speech standard speech-to-text REST integration.

This module deliberately uses the same Speech resource and audio validation
as Pronunciation Assessment, but sends no Pronunciation-Assessment header.
"""

import json
import logging
import os
import urllib.error
import urllib.request

from voice_assessment import (
    AZURE_TIMEOUT_SECONDS,
    VoiceAssessmentError,
    _build_endpoint,
    _load_supported_locales,
    _validate_audio,
)


def _normalize_words(words: list) -> list[dict]:
    """Normalize optional word-level timing data returned by Azure STT."""
    normalized = []

    for item in words:
        if not isinstance(item, dict):
            continue

        offset = item.get("Offset")
        duration = item.get("Duration")

        normalized.append({
            "word": item.get("Word", ""),
            "confidence": item.get("Confidence"),
            "offset_ms": (
                round(offset / 10000, 2)
                if isinstance(offset, (int, float))
                else None
            ),
            "duration_ms": (
                round(duration / 10000, 2)
                if isinstance(duration, (int, float))
                else None
            ),
        })

    return normalized


def recognize_speech(locale: str, audio_bytes: bytes) -> dict:
    """Recognize speech from WAV audio without a reference transcript."""
    if not isinstance(locale, str) or not locale.strip():
        raise VoiceAssessmentError(
            "locale_missing",
            "Locale is required.",
            400,
        )

    locale = locale.strip()

    if locale not in _load_supported_locales():
        raise VoiceAssessmentError(
            "locale_not_supported",
            f"Speech recognition does not support locale '{locale}'.",
            400,
        )

    _validate_audio(audio_bytes)

    speech_key = os.environ.get("AZURE_SPEECH_KEY")
    speech_region = os.environ.get("AZURE_SPEECH_REGION")

    if not speech_key or not speech_region:
        logging.error("Azure Speech configuration is missing")
        raise VoiceAssessmentError(
            "speech_service_not_configured",
            "Azure Speech service is not configured.",
            500,
        )

    request = urllib.request.Request(
        _build_endpoint(speech_region, locale),
        data=bytes(audio_bytes),
        headers={
            "Ocp-Apim-Subscription-Key": speech_key,
            "Content-Type": (
                "audio/wav; codecs=audio/pcm; samplerate=16000"
            ),
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=AZURE_TIMEOUT_SECONDS,
        ) as response:
            response_body = response.read()

    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            code, message, status = (
                "speech_service_auth_error",
                "Azure Speech authentication failed. Check the Speech resource key and region.",
                502,
            )
        elif error.code == 429:
            code, message, status = (
                "speech_service_rate_limited",
                "Azure Speech request limit was reached. Please try again later.",
                503,
            )
        elif error.code == 400:
            code, message, status = (
                "speech_service_bad_request",
                "Azure Speech rejected the recognition request.",
                502,
            )
        else:
            code, message, status = (
                "speech_service_error",
                "Azure Speech could not complete speech recognition.",
                502,
            )

        logging.warning(
            "Azure Speech returned HTTP %s for standard recognition, locale %s",
            error.code,
            locale,
        )
        raise VoiceAssessmentError(code, message, status)

    except (urllib.error.URLError, TimeoutError, OSError):
        logging.exception("Azure Speech recognition request failed")
        raise VoiceAssessmentError(
            "speech_service_unavailable",
            "Azure Speech service is temporarily unavailable.",
            502,
        )

    try:
        azure_result = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logging.error("Azure Speech returned invalid JSON for recognition")
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an invalid response.",
            502,
        )

    if not isinstance(azure_result, dict):
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an unexpected response.",
            502,
        )

    recognition_status = azure_result.get("RecognitionStatus")
    candidates = azure_result.get("NBest")

    if (
        recognition_status != "Success"
        or not isinstance(candidates, list)
        or not candidates
        or not isinstance(candidates[0], dict)
    ):
        logging.info(
            "Azure Speech did not recognize speech: status=%s",
            recognition_status,
        )
        raise VoiceAssessmentError(
            "no_speech_detected",
            "No speech could be recognized in the recording.",
            422,
        )

    best_result = candidates[0]
    words = best_result.get("Words")
    if not isinstance(words, list):
        words = []

    return {
        "success": True,
        "recognized_text": best_result.get("Display", ""),
        "confidence": best_result.get("Confidence"),
        "words": _normalize_words(words),
        "metadata": {
            "locale": locale,
            "recognition_mode": "standard",
            "recognition_status": recognition_status,
        },
    }

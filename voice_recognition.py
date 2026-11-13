"""Azure Speech standard speech-to-text integration using the Speech SDK.

This module recognizes speech without a reference transcript and requests
word-level timestamps. Pronunciation Assessment remains implemented separately.
"""

import json
import logging
import os
import tempfile

import azure.cognitiveservices.speech as speechsdk

from voice_assessment import (
    VoiceAssessmentError,
    _load_supported_locales,
    _validate_audio,
)


def _normalize_words(words: list) -> list[dict]:
    """Normalize Azure detailed word results and convert HNS to milliseconds."""
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


def _parse_detailed_result(result) -> tuple[dict, list[dict]]:
    """Extract the best hypothesis and word timings from the SDK JSON result."""
    try:
        payload = json.loads(result.json)
    except (AttributeError, TypeError, json.JSONDecodeError):
        logging.exception("Azure Speech SDK returned invalid detailed JSON")
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an invalid recognition result.",
            502,
        )

    if not isinstance(payload, dict):
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an unexpected recognition result.",
            502,
        )

    candidates = payload.get("NBest")
    if not isinstance(candidates, list) or not candidates:
        logging.warning(
            "Azure Speech detailed result has no NBest candidates; fields=%s",
            sorted(payload.keys()),
        )
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech did not return detailed recognition data.",
            502,
        )

    best_result = candidates[0]
    if not isinstance(best_result, dict):
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an unexpected recognition candidate.",
            502,
        )

    words = best_result.get("Words")
    if not isinstance(words, list):
        logging.warning(
            "Azure Speech detailed result contains no word timings; fields=%s",
            sorted(best_result.keys()),
        )
        words = []

    return best_result, _normalize_words(words)


def recognize_speech(locale: str, audio_bytes: bytes) -> dict:
    """Recognize a WAV recording without a reference transcript."""
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

    temp_path = None

    try:
        # The SDK file input accepts a path. Use a temporary WAV file and
        # always remove it after recognition.
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".wav",
            delete=False,
        ) as audio_file:
            audio_file.write(bytes(audio_bytes))
            temp_path = audio_file.name

        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key,
            region=speech_region,
        )
        speech_config.speech_recognition_language = locale
        speech_config.request_word_level_timestamps()

        audio_config = speechsdk.audio.AudioConfig(filename=temp_path)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )

        result = recognizer.recognize_once()

    except Exception:
        logging.exception("Azure Speech SDK recognition request failed")
        raise VoiceAssessmentError(
            "speech_service_unavailable",
            "Azure Speech service is temporarily unavailable.",
            502,
        )

    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                logging.warning("Unable to remove temporary speech audio file")

    if result.reason == speechsdk.ResultReason.NoMatch:
        logging.info("Azure Speech SDK found no speech for locale %s", locale)
        raise VoiceAssessmentError(
            "no_speech_detected",
            "No speech could be recognized in the recording.",
            422,
        )

    if result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        logging.warning(
            "Azure Speech SDK canceled recognition: reason=%s, details=%s",
            details.reason,
            details.error_details,
        )
        if details.reason == speechsdk.CancellationReason.Error:
            raise VoiceAssessmentError(
                "speech_service_error",
                "Azure Speech could not complete speech recognition.",
                502,
            )

        raise VoiceAssessmentError(
            "no_speech_detected",
            "No speech could be recognized in the recording.",
            422,
        )

    if result.reason != speechsdk.ResultReason.RecognizedSpeech:
        logging.warning(
            "Azure Speech SDK returned unexpected result reason: %s",
            result.reason,
        )
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an unexpected recognition result.",
            502,
        )

    best_result, words = _parse_detailed_result(result)

    return {
        "success": True,
        "recognized_text": result.text,
        "confidence": best_result.get("Confidence"),
        "words": words,
        "metadata": {
            "locale": locale,
            "recognition_mode": "standard",
            "recognition_status": "Success",
            "recognition_engine": "speech_sdk",
        },
    }

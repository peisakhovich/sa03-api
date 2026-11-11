"""Azure Speech Pronunciation Assessment REST integration.

This module deliberately uses only the Python standard library.
"""

import base64
import io
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path


MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_AUDIO_SECONDS = 30.0
MAX_REFERENCE_TEXT_LENGTH = 500
AZURE_TIMEOUT_SECONDS = 45
ASSESSMENT_VERSION = "1.0"

LOCALE_CONFIG_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "azure_pronunciation_locales.json"
)


class VoiceAssessmentError(Exception):
    """Expected voice-assessment error with an HTTP status code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@lru_cache(maxsize=1)
def _load_supported_locales() -> frozenset[str]:
    """Load the authoritative Pronunciation Assessment locale allowlist."""

    try:
        with LOCALE_CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, json.JSONDecodeError):
        logging.exception("Unable to load Pronunciation Assessment locale config")
        raise VoiceAssessmentError(
            "locale_config_error",
            "Pronunciation Assessment locale configuration is unavailable.",
            500,
        )

    locales = config.get("supported_locales") if isinstance(config, dict) else None

    if (
        not isinstance(locales, list)
        or not locales
        or any(not isinstance(locale, str) or not locale for locale in locales)
    ):
        logging.error("Invalid supported_locales in %s", LOCALE_CONFIG_PATH)
        raise VoiceAssessmentError(
            "locale_config_error",
            "Pronunciation Assessment locale configuration is invalid.",
            500,
        )

    return frozenset(locales)


def _validate_audio(audio_bytes: bytes) -> None:
    """Validate WAV container and the PCM format expected by Azure."""

    if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
        raise VoiceAssessmentError(
            "audio_missing",
            "Audio file is missing or empty.",
            400,
        )

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise VoiceAssessmentError(
            "audio_too_large",
            "Audio file exceeds the 2 MB limit.",
            413,
        )

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            compression = wav_file.getcomptype()

            if (
                channels != 1
                or sample_width != 2
                or sample_rate != 16000
                or compression != "NONE"
            ):
                raise VoiceAssessmentError(
                    "invalid_audio_format",
                    "Audio must be uncompressed WAV, PCM 16-bit, 16 kHz, mono.",
                    400,
                )

            if frame_count <= 0:
                raise VoiceAssessmentError(
                    "audio_empty",
                    "Audio contains no recorded samples.",
                    400,
                )

            duration_seconds = frame_count / float(sample_rate)

            if duration_seconds > MAX_AUDIO_SECONDS:
                raise VoiceAssessmentError(
                    "audio_too_long",
                    "Audio recording exceeds the 30-second limit.",
                    413,
                )

    except VoiceAssessmentError:
        raise
    except (wave.Error, EOFError, OSError):
        raise VoiceAssessmentError(
            "invalid_wav",
            "The uploaded file is not a valid WAV audio recording.",
            400,
        )


def _validate_request(
    reference_text: str,
    locale: str,
    audio_bytes: bytes,
) -> tuple[str, str]:
    if not isinstance(reference_text, str) or not reference_text.strip():
        raise VoiceAssessmentError(
            "reference_text_missing",
            "Reference text is required.",
            400,
        )

    reference_text = reference_text.strip()

    if len(reference_text) > MAX_REFERENCE_TEXT_LENGTH:
        raise VoiceAssessmentError(
            "reference_text_too_long",
            "Reference text exceeds the 500-character limit.",
            400,
        )

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
            f"Pronunciation Assessment does not support locale '{locale}'.",
            400,
        )

    _validate_audio(audio_bytes)

    return reference_text, locale


def _build_endpoint(region: str, locale: str) -> str:
    query = urllib.parse.urlencode({
        "language": locale,
        "format": "detailed",
    })

    return (
        f"https://{region}.stt.speech.microsoft.com"
        "/speech/recognition/conversation/cognitiveservices/v1"
        f"?{query}"
    )


def _count_word_errors(words: list) -> dict:
    """Count Azure word-level miscues from the ErrorType field."""
    counts = {
        "mispronunciations": 0,
        "omissions": 0,
        "insertions": 0,
    }

    error_type_map = {
        "Mispronunciation": "mispronunciations",
        "Omission": "omissions",
        "Insertion": "insertions",
    }

    for word in words:
        if not isinstance(word, dict):
            continue

        target = error_type_map.get(word.get("ErrorType"))
        if target:
            counts[target] += 1

    return counts


def _normalize_words(words: list) -> list[dict]:
    """Convert Azure word results into a stable API response structure."""
    normalized = []

    for item in words:
        if not isinstance(item, dict):
            continue

        offset = item.get("Offset")
        duration = item.get("Duration")

        normalized.append({
            "word": item.get("Word", ""),
            "accuracy_score": item.get("AccuracyScore"),
            "error_type": item.get("ErrorType", "None"),
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
            "confidence": item.get("Confidence"),
        })

    return normalized


def _azure_error_message(status_code: int) -> tuple[str, str, int]:
    if status_code in (401, 403):
        return (
            "speech_service_auth_error",
            "Azure Speech authentication failed. Check the Speech resource key and region.",
            502,
        )

    if status_code == 429:
        return (
            "speech_service_rate_limited",
            "Azure Speech request limit was reached. Please try again later.",
            503,
        )

    if status_code == 400:
        return (
            "speech_service_bad_request",
            "Azure Speech rejected the assessment request.",
            502,
        )

    return (
        "speech_service_error",
        "Azure Speech could not complete the pronunciation assessment.",
        502,
    )


def assess_pronunciation(
    reference_text: str,
    locale: str,
    audio_bytes: bytes,
) -> dict:
    """Send a WAV recording to Azure and return normalized assessment data."""

    reference_text, locale = _validate_request(
        reference_text,
        locale,
        audio_bytes,
    )

    speech_key = os.environ.get("AZURE_SPEECH_KEY")
    speech_region = os.environ.get("AZURE_SPEECH_REGION")

    if not speech_key or not speech_region:
        logging.error("Azure Speech configuration is missing")
        raise VoiceAssessmentError(
            "speech_service_not_configured",
            "Azure Speech service is not configured.",
            500,
        )

    assessment_config = {
        "ReferenceText": reference_text,
        "GradingSystem": "HundredMark",
        "Granularity": "Word",
        "Dimension": "Comprehensive",
        "EnableMiscue": True,
    }

    assessment_header = base64.b64encode(
        json.dumps(
            assessment_config,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")

    request = urllib.request.Request(
        _build_endpoint(speech_region, locale),
        data=bytes(audio_bytes),
        headers={
            "Ocp-Apim-Subscription-Key": speech_key,
            "Content-Type": (
                "audio/wav; codecs=audio/pcm; samplerate=16000"
            ),
            "Accept": "application/json",
            "Pronunciation-Assessment": assessment_header,
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
        code, message, status = _azure_error_message(error.code)
        logging.warning(
            "Azure Speech returned HTTP %s for locale %s",
            error.code,
            locale,
        )
        raise VoiceAssessmentError(code, message, status)

    except (urllib.error.URLError, TimeoutError, OSError):
        logging.exception("Azure Speech request failed")
        raise VoiceAssessmentError(
            "speech_service_unavailable",
            "Azure Speech service is temporarily unavailable.",
            502,
        )

    try:
        azure_result = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logging.error("Azure Speech returned an invalid JSON response")
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

    if recognition_status != "Success" or not isinstance(candidates, list) or not candidates:
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

    if not isinstance(best_result, dict):
        raise VoiceAssessmentError(
            "speech_service_invalid_response",
            "Azure Speech returned an unexpected assessment result.",
            502,
        )

    # Azure returns the overall assessment scores directly in NBest[0].
    words = best_result.get("Words")
    if not isinstance(words, list):
        words = []

    return {
        "success": True,
        "assessment": {
            "pronunciation_score": best_result.get("PronScore"),
            "accuracy_score": best_result.get("AccuracyScore"),
            "fluency_score": best_result.get("FluencyScore"),
            "completeness_score": best_result.get("CompletenessScore"),
        },
        "recognized_text": best_result.get("Display", ""),
        "errors": _count_word_errors(words),
        "words": _normalize_words(words),
        "metadata": {
            "locale": locale,
            "assessment_version": ASSESSMENT_VERSION,
        },
    }

"""OpenAI-compatible semantic timeline enhancement and deterministic H3 compilation."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .enhancer_config import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MODEL_ENV,
    TIMEOUT_ENV,
    ProviderConfigError,
    get_default_provider_config_store,
)
from .prompt_builder import normalize_character_context_data

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_TIMELINE_BEATS = 12
LEGACY_SUBJECT_ROLES = {"<Subject 1>": {"type": "character", "name": ""}}

_SUBJECT_TOKEN_RE = re.compile(r"<Subject\s+(\d+)>")
_SUBJECT_LIKE_RE = re.compile(r"<\s*Subject\b[^>]*>", re.IGNORECASE)
_BARE_SUBJECT_RE = re.compile(r"(?<!<)\bSubject\s+(\d+)\b(?!>)", re.IGNORECASE)
_SHOT_RE = re.compile(r"\[\s*Shot\s+\d+\s*]", re.IGNORECASE)
_CLOCK_RANGE_RE = re.compile(r"\b\d{1,2}:\d{2}\s*[-–—]\s*\d{1,2}:\d{2}\b")
_SECOND_RANGE_RE = re.compile(
    r"\[\s*\d+\s*(?:s|sec|seconds)?\s*[-–—]\s*"
    r"\d+\s*(?:s|sec|seconds)?\s*]",
    re.IGNORECASE,
)
_DIALOGUE_TAG_RE = re.compile(r"</?d\b", re.IGNORECASE)
_SPEAKER_ID_RE = re.compile(r"\(\s*S\d+\s*\)", re.IGNORECASE)
_SUBJECT_ANNOTATION_RE = re.compile(r"<Subject\s+\d+>\s*\([^\n)]*\)")


class PromptEnhancerError(RuntimeError):
    """A safe, user-facing prompt-enhancement failure."""


@dataclass(frozen=True)
class EnhancerConfig:
    api_key: str = field(repr=False)
    endpoint: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class _ProviderHTTPError(Exception):
    status: int
    detail: str


_LOGGER = logging.getLogger(__name__)


def _redact(value: object, api_key: str) -> str:
    text = str(value)
    return text.replace(api_key, "[redacted]") if api_key else text


def _chat_endpoint(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PromptEnhancerError(
            f"{BASE_URL_ENV} must be a complete HTTP or HTTPS URL."
        )
    if parsed.query or parsed.fragment:
        raise PromptEnhancerError(
            f"{BASE_URL_ENV} must not contain a query string or fragment."
        )
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return cleaned + "/chat/completions"


def load_enhancer_config() -> EnhancerConfig:
    try:
        resolved = get_default_provider_config_store().resolve()
    except ProviderConfigError as exc:
        raise PromptEnhancerError(str(exc)) from exc
    if not resolved.api_key:
        raise PromptEnhancerError(
            "Prompt enhancer API key is not configured. Add one in ComfyUI Settings "
            f"under H3 Character Ref Builder, or set {API_KEY_ENV}."
        )
    return EnhancerConfig(
        api_key=resolved.api_key,
        endpoint=_chat_endpoint(resolved.base_url),
        model=resolved.model,
        timeout_seconds=resolved.timeout_seconds,
    )


def max_beats_for_duration(duration_seconds: int) -> int:
    """Return the safety ceiling without imposing a semantic beat count."""
    return min(duration_seconds, MAX_TIMELINE_BEATS)


def _character_subjects(
    subject_roles: dict[str, dict[str, str]] | None,
) -> list[str]:
    roles = subject_roles if subject_roles is not None else LEGACY_SUBJECT_ROLES
    subjects = [
        token
        for token, role in roles.items()
        if isinstance(role, dict) and role.get("type") == "character"
    ]
    if not subjects:
        raise PromptEnhancerError(
            "Prompt enhancer character_context contains no character Subjects."
        )
    return subjects


def _response_schema(
    *,
    duration_seconds: int,
    subject_roles: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    character_subjects = _character_subjects(subject_roles)
    event_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["dialogue", "vocalization"]},
            "subject": {"type": "string", "enum": character_subjects},
            "language": {"type": "string"},
            "delivery": {"type": "string"},
            "content": {"type": "string", "minLength": 1},
        },
        "required": ["kind", "subject", "language", "delivery", "content"],
    }
    beat_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "start_seconds": {"type": "integer", "minimum": 0},
            "end_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": duration_seconds,
            },
            "description": {"type": "string", "minLength": 1},
            "vocal_events": {"type": "array", "items": event_schema},
        },
        "required": [
            "start_seconds",
            "end_seconds",
            "description",
            "vocal_events",
        ],
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "h3_semantic_timeline_v2",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "beats": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": max_beats_for_duration(duration_seconds),
                        "items": beat_schema,
                    },
                    "additional_soundscape": {"type": "string"},
                },
                "required": ["beats", "additional_soundscape"],
            },
        },
    }


def _provider_task(
    *,
    scene_definition: str,
    default_soundscape: str = "",
    subject_roles: dict[str, dict[str, str]] | None,
    duration_seconds: int,
    action_idea: str,
    additional_notes: str,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "duration_seconds": duration_seconds,
        "action_idea": action_idea,
        "subject_roles": (
            subject_roles if subject_roles is not None else LEGACY_SUBJECT_ROLES
        ),
        "default_soundscape": default_soundscape.strip(),
    }
    if scene_definition.strip():
        task["scene_definition"] = scene_definition.strip()
    if additional_notes.strip():
        task["additional_notes"] = additional_notes.strip()
    return task


def _request_payload(
    *,
    config: EnhancerConfig,
    system_prompt: str,
    scene_definition: str,
    default_soundscape: str = "",
    subject_roles: dict[str, dict[str, str]] | None = None,
    duration_seconds: int,
    action_idea: str,
    additional_notes: str,
    structured: bool,
) -> dict[str, Any]:
    task = _provider_task(
        scene_definition=scene_definition,
        default_soundscape=default_soundscape,
        subject_roles=subject_roles,
        duration_seconds=duration_seconds,
        action_idea=action_idea,
        additional_notes=additional_notes,
    )
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(task, ensure_ascii=False, indent=2),
            },
        ],
    }
    if structured:
        payload["response_format"] = _response_schema(
            duration_seconds=duration_seconds,
            subject_roles=subject_roles,
        )
    return payload


def _corrective_payload(
    *,
    original_payload: dict[str, Any],
    previous_content: object,
    validation_error: str,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    messages = list(original_payload["messages"])
    if isinstance(previous_content, dict):
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(previous_content, ensure_ascii=False),
            }
        )
    elif isinstance(previous_content, str) and previous_content.strip():
        messages.append({"role": "assistant", "content": previous_content})
    correction = {
        "instruction": (
            "Your previous response failed validation. Return one corrected structured "
            "timeline for the original request. Preserve the requested action and exact "
            "dialogue. Do not add new actions or final H3 formatting."
        ),
        "validation_error": validation_error,
    }
    messages.append(
        {
            "role": "user",
            "content": json.dumps(correction, ensure_ascii=False, indent=2),
        }
    )
    payload: dict[str, Any] = {
        "model": original_payload["model"],
        "messages": messages,
    }
    if response_schema is not None:
        payload["response_format"] = response_schema
    return payload


def _provider_detail(raw: bytes, api_key: str) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            text = error["message"]
        elif isinstance(error, str):
            text = error
    except json.JSONDecodeError:
        pass
    return _redact(text[:500] or "No provider error detail was returned.", api_key)


def _request_once(config: EnhancerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        config.endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        raise _ProviderHTTPError(
            exc.code, _provider_detail(raw, config.api_key)
        ) from exc
    except TimeoutError as exc:
        raise PromptEnhancerError(
            f"Prompt enhancer request timed out after {config.timeout_seconds:g} seconds."
        ) from exc
    except URLError as exc:
        reason = _redact(exc.reason, config.api_key)
        if isinstance(exc.reason, TimeoutError):
            raise PromptEnhancerError(
                f"Prompt enhancer request timed out after {config.timeout_seconds:g} seconds."
            ) from exc
        raise PromptEnhancerError(
            f"Network failure while contacting the prompt enhancer provider: {reason}"
        ) from exc
    except OSError as exc:
        raise PromptEnhancerError(
            "Network failure while contacting the prompt enhancer provider: "
            + _redact(exc, config.api_key)
        ) from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise PromptEnhancerError(
            "Prompt enhancer provider response was unexpectedly large."
        )
    try:
        response_payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptEnhancerError(
            "Prompt enhancer provider returned malformed JSON."
        ) from exc
    if not isinstance(response_payload, dict):
        raise PromptEnhancerError(
            "Prompt enhancer provider returned an invalid response object."
        )
    return response_payload


def _raise_http_failure(error: _ProviderHTTPError) -> None:
    if error.status in {401, 403}:
        raise PromptEnhancerError(
            "Prompt enhancer authentication failed (HTTP " + str(error.status) + ")."
        ) from error
    if error.status == 429:
        raise PromptEnhancerError(
            "Prompt enhancer provider rate limit exceeded (HTTP 429)."
        ) from error
    if 500 <= error.status <= 599:
        raise PromptEnhancerError(
            f"Prompt enhancer provider is unavailable (HTTP {error.status})."
        ) from error
    raise PromptEnhancerError(
        f"Prompt enhancer provider request failed (HTTP {error.status}): {error.detail}"
    ) from error


def _message_content(payload: dict[str, Any]) -> object:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise PromptEnhancerError(
            "Prompt enhancer provider response is missing choices[0]."
        )
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise PromptEnhancerError(
            "Prompt enhancer provider response is missing choices[0].message."
        )
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return parsed
    content = message.get("content")
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") in {"text", "output_text"}
            and isinstance(block.get("text"), str)
        ]
        return "".join(parts)
    return content


def _decode_structured_content(content: object) -> dict[str, Any]:
    if isinstance(content, dict):
        payload = content
    elif isinstance(content, str):
        cleaned = content.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            lines = cleaned.splitlines()
            if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"}:
                cleaned = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise PromptEnhancerError(
                "Prompt enhancer returned malformed structured JSON content."
            ) from exc
    else:
        raise PromptEnhancerError(
            "Prompt enhancer returned no structured message content."
        )
    if not isinstance(payload, dict):
        raise PromptEnhancerError(
            "Prompt enhancer structured content must be a JSON object."
        )
    return payload


def _normalize_description_subjects(
    description: str,
    subject_roles: dict[str, dict[str, str]],
) -> str:
    def replace_bare(match: re.Match[str]) -> str:
        token = f"<Subject {int(match.group(1))}>"
        return token if token in subject_roles else match.group(0)

    normalized = _BARE_SUBJECT_RE.sub(replace_bare, description)
    for token, role in subject_roles.items():
        name = role.get("name", "").strip()
        if name:
            named_token = re.compile(
                re.escape(token) + r"\s*\(\s*" + re.escape(name) + r"\s*\)"
            )
            normalized = named_token.sub(token, normalized)
    return normalized


def _validate_description(
    description: object,
    *,
    beat_number: int,
    subject_roles: dict[str, dict[str, str]],
) -> str:
    path = f"beats[{beat_number - 1}].description"
    if not isinstance(description, str) or not description.strip():
        raise PromptEnhancerError(f"{path} must be a non-empty string.")
    normalized = _normalize_description_subjects(description.strip(), subject_roles)
    if _SHOT_RE.search(normalized):
        raise PromptEnhancerError(f"{path} must not contain a [Shot N] marker.")
    if _CLOCK_RANGE_RE.search(normalized) or _SECOND_RANGE_RE.search(normalized):
        raise PromptEnhancerError(f"{path} must not contain formatted timestamps.")
    if _DIALOGUE_TAG_RE.search(normalized):
        raise PromptEnhancerError(f"{path} must not contain <d> dialogue tags.")
    if _SPEAKER_ID_RE.search(normalized):
        raise PromptEnhancerError(f"{path} must not contain H3 speaker IDs.")
    if _SUBJECT_ANNOTATION_RE.search(normalized):
        raise PromptEnhancerError(
            f"{path} contains an unrecognized Subject annotation."
        )
    allowed = set(subject_roles)
    for match in _SUBJECT_LIKE_RE.finditer(normalized):
        token = match.group(0)
        canonical = _SUBJECT_TOKEN_RE.fullmatch(token)
        if canonical is None or token not in allowed:
            raise PromptEnhancerError(
                f"{path} contains unknown Subject token {token!r}."
            )
    bare = _BARE_SUBJECT_RE.search(normalized)
    if bare:
        raise PromptEnhancerError(
            f"{path} contains unknown bare Subject {bare.group(0)!r}."
        )
    return normalized


def _validate_vocal_event(
    event: object,
    *,
    beat_number: int,
    event_number: int,
    character_subjects: set[str],
) -> dict[str, str]:
    path = f"beats[{beat_number - 1}].vocal_events[{event_number - 1}]"
    required = {"kind", "subject", "language", "delivery", "content"}
    if not isinstance(event, dict) or set(event) != required:
        raise PromptEnhancerError(
            f"{path} must contain exactly kind, subject, language, delivery, and content."
        )
    if event["kind"] not in {"dialogue", "vocalization"}:
        raise PromptEnhancerError(f"{path}.kind must be dialogue or vocalization.")
    if event["subject"] not in character_subjects:
        raise PromptEnhancerError(
            f"{path}.subject must reference an authoritative character Subject."
        )
    for key in ("language", "delivery", "content"):
        if not isinstance(event[key], str):
            raise PromptEnhancerError(f"{path}.{key} must be a string.")
    if not event["content"].strip():
        raise PromptEnhancerError(f"{path}.content must not be empty.")
    if _DIALOGUE_TAG_RE.search(event["content"]) or _SPEAKER_ID_RE.search(
        event["content"]
    ):
        raise PromptEnhancerError(
            f"{path}.content must not contain final H3 dialogue formatting."
        )
    if event["kind"] == "dialogue":
        if not event["language"].strip():
            raise PromptEnhancerError(
                f"{path}.language must not be empty for dialogue."
            )
    else:
        if event["language"].strip() or event["delivery"].strip():
            raise PromptEnhancerError(
                f"{path} vocalization language and delivery must be empty."
            )
        if _SUBJECT_LIKE_RE.search(event["content"]) or _BARE_SUBJECT_RE.search(
            event["content"]
        ):
            raise PromptEnhancerError(
                f"{path}.content must not repeat a Subject token."
            )
    content = (
        event["content"] if event["kind"] == "dialogue" else event["content"].strip()
    )
    return {
        "kind": event["kind"],
        "subject": event["subject"],
        "language": event["language"].strip(),
        "delivery": event["delivery"].strip(),
        "content": content,
    }


def _contains_dialogue_text(soundscape: str, dialogue: str) -> bool:
    dialogue = dialogue.strip()
    return bool(
        re.search(
            r"(?<!\w)" + re.escape(dialogue.casefold()) + r"(?!\w)",
            soundscape.casefold(),
        )
    )


def parse_enhancement_content(
    content: object,
    *,
    duration_seconds: int,
    subject_roles: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Parse, normalize, and validate one semantic provider timeline."""
    if not 1 <= duration_seconds <= 60:
        raise PromptEnhancerError("Duration must be between 1 and 60 seconds.")
    roles = subject_roles if subject_roles is not None else LEGACY_SUBJECT_ROLES
    character_subjects = set(_character_subjects(roles))
    payload = _decode_structured_content(content)
    if set(payload) != {"beats", "additional_soundscape"}:
        raise PromptEnhancerError(
            "Structured timeline must contain exactly beats and additional_soundscape."
        )
    beats = payload["beats"]
    if not isinstance(beats, list) or not beats:
        raise PromptEnhancerError("Structured timeline beats must not be empty.")
    maximum = max_beats_for_duration(duration_seconds)
    if len(beats) > maximum:
        raise PromptEnhancerError(
            f"Structured timeline has {len(beats)} beats; maximum is {maximum}."
        )
    additional = payload["additional_soundscape"]
    if not isinstance(additional, str):
        raise PromptEnhancerError(
            "Structured timeline additional_soundscape must be a string."
        )
    normalized_beats: list[dict[str, Any]] = []
    previous_end = 0
    dialogue_lines: list[str] = []
    beat_fields = {"start_seconds", "end_seconds", "description", "vocal_events"}
    for index, beat in enumerate(beats, start=1):
        path = f"beats[{index - 1}]"
        if not isinstance(beat, dict) or set(beat) != beat_fields:
            raise PromptEnhancerError(
                f"{path} must contain exactly start_seconds, end_seconds, "
                "description, and vocal_events."
            )
        start = beat["start_seconds"]
        end = beat["end_seconds"]
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
        ):
            raise PromptEnhancerError(f"{path} start/end seconds must be integers.")
        if start < 0:
            raise PromptEnhancerError(f"{path}.start_seconds must be at least 0.")
        if end <= start:
            raise PromptEnhancerError(f"{path} must have positive duration.")
        if index == 1 and start != 0:
            raise PromptEnhancerError(
                "The first timeline beat must start at 0 seconds."
            )
        if start != previous_end:
            relationship = "gap" if start > previous_end else "overlap or bad order"
            raise PromptEnhancerError(
                f"{path} creates a timeline {relationship}: expected start "
                f"{previous_end}, received {start}."
            )
        description = _validate_description(
            beat["description"],
            beat_number=index,
            subject_roles=roles,
        )
        events = beat["vocal_events"]
        if not isinstance(events, list):
            raise PromptEnhancerError(f"{path}.vocal_events must be an array.")
        normalized_events = [
            _validate_vocal_event(
                event,
                beat_number=index,
                event_number=event_index,
                character_subjects=character_subjects,
            )
            for event_index, event in enumerate(events, start=1)
        ]
        dialogue_lines.extend(
            event["content"]
            for event in normalized_events
            if event["kind"] == "dialogue"
        )
        normalized_beats.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "description": description,
                "vocal_events": normalized_events,
            }
        )
        previous_end = end
    if previous_end != duration_seconds:
        raise PromptEnhancerError(
            "The final timeline beat must end at duration_seconds "
            f"({duration_seconds}); received {previous_end}."
        )
    clean_additional = additional.strip()
    if _DIALOGUE_TAG_RE.search(clean_additional):
        raise PromptEnhancerError(
            "additional_soundscape must not contain formatted spoken dialogue."
        )
    for line in dialogue_lines:
        if _contains_dialogue_text(clean_additional, line):
            raise PromptEnhancerError(
                "additional_soundscape must not repeat spoken dialogue content."
            )
    return {
        "beats": normalized_beats,
        "additional_soundscape": clean_additional,
    }


def _format_clock(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def compile_detailed_description(plan: dict[str, Any]) -> str:
    """Compile a validated semantic plan into deterministic MiniMax H3 syntax."""
    speaker_ids: dict[str, str] = {}
    beat_blocks: list[str] = []
    for beat in plan["beats"]:
        lines = [
            f"{_format_clock(beat['start_seconds'])}-{_format_clock(beat['end_seconds'])}",
            beat["description"],
        ]
        for event in beat["vocal_events"]:
            subject = event["subject"]
            if event["kind"] == "dialogue":
                if subject not in speaker_ids:
                    speaker_ids[subject] = f"S{len(speaker_ids) + 1}"
                delivery = f" {event['delivery']}" if event["delivery"] else ""
                lines.append(
                    f"{subject} ({speaker_ids[subject]}) says{delivery}: "
                    f"<d>[{event['language']}] {event['content']}</d>"
                )
            else:
                vocalization = f"{subject} {event['content']}"
                if vocalization[-1] not in ".!?”’":
                    vocalization += "."
                lines.append(vocalization)
        beat_blocks.append("\n".join(lines))
    return "[Shot 1]\n\n" + "\n\n".join(beat_blocks)


def _content_contains_secret(content: object, api_key: str) -> bool:
    if not api_key:
        return False
    try:
        serialized = json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        serialized = str(content)
    return api_key in serialized


def _parse_provider_response(
    response: dict[str, Any],
    *,
    config: EnhancerConfig,
    duration_seconds: int,
    subject_roles: dict[str, dict[str, str]] | None,
) -> tuple[dict[str, Any], object]:
    content = _message_content(response)
    if _content_contains_secret(content, config.api_key):
        raise PromptEnhancerError(
            "Prompt enhancer provider response contained sensitive credential data "
            "and was rejected."
        )
    plan = parse_enhancement_content(
        content,
        duration_seconds=duration_seconds,
        subject_roles=subject_roles,
    )
    return plan, content


def _request_enhancement(
    *,
    config: EnhancerConfig,
    system_prompt: str,
    scene_definition: str,
    default_soundscape: str = "",
    subject_roles: dict[str, dict[str, str]] | None = None,
    duration_seconds: int,
    action_idea: str,
    additional_notes: str,
) -> dict[str, str]:
    strict_payload = _request_payload(
        config=config,
        system_prompt=system_prompt,
        scene_definition=scene_definition,
        default_soundscape=default_soundscape,
        subject_roles=subject_roles,
        duration_seconds=duration_seconds,
        action_idea=action_idea,
        additional_notes=additional_notes,
        structured=True,
    )
    active_payload = strict_payload
    response_schema: dict[str, Any] | None = strict_payload["response_format"]
    try:
        response = _request_once(config, strict_payload)
    except _ProviderHTTPError as error:
        if error.status not in {400, 422}:
            _raise_http_failure(error)
        active_payload = _request_payload(
            config=config,
            system_prompt=system_prompt,
            scene_definition=scene_definition,
            default_soundscape=default_soundscape,
            subject_roles=subject_roles,
            duration_seconds=duration_seconds,
            action_idea=action_idea,
            additional_notes=additional_notes,
            structured=False,
        )
        response_schema = None
        try:
            response = _request_once(config, active_payload)
        except _ProviderHTTPError as fallback_error:
            _raise_http_failure(fallback_error)

    previous_content: object = None
    try:
        plan, previous_content = _parse_provider_response(
            response,
            config=config,
            duration_seconds=duration_seconds,
            subject_roles=subject_roles,
        )
    except PromptEnhancerError as first_error:
        if "sensitive credential data" in str(first_error):
            raise
        try:
            previous_content = _message_content(response)
        except PromptEnhancerError:
            previous_content = None
        correction_payload = _corrective_payload(
            original_payload=active_payload,
            previous_content=previous_content,
            validation_error=str(first_error),
            response_schema=response_schema,
        )
        try:
            corrected_response = _request_once(config, correction_payload)
        except _ProviderHTTPError as correction_error:
            _raise_http_failure(correction_error)
        try:
            plan, _ = _parse_provider_response(
                corrected_response,
                config=config,
                duration_seconds=duration_seconds,
                subject_roles=subject_roles,
            )
        except PromptEnhancerError as second_error:
            raise PromptEnhancerError(
                "Prompt enhancer returned an invalid semantic timeline after one "
                f"corrective retry: {second_error}"
            ) from second_error

    return {
        "detailed_description": compile_detailed_description(plan),
        "additional_soundscape": plan["additional_soundscape"],
    }


def get_enhancement(
    *,
    character_context: dict[str, Any],
    duration_seconds: int,
    system_prompt: str,
    action_idea: str,
    additional_notes: str,
) -> dict[str, str]:
    if not 1 <= duration_seconds <= 60:
        raise PromptEnhancerError("Duration must be between 1 and 60 seconds.")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise PromptEnhancerError("System Prompt is required.")
    clean_action = action_idea.strip()
    if not clean_action:
        raise PromptEnhancerError("Action Idea is required.")
    clean_notes = additional_notes.strip()
    context = normalize_character_context_data(character_context)
    scene_definition = str(context["scene_definition"]).strip()
    default_soundscape = str(context["default_soundscape"]).strip()
    subject_roles = context["subject_roles"]
    config = load_enhancer_config()
    request_id = uuid.uuid4().hex[:8]
    _LOGGER.info("[H3 Prompt Enhancer] request %s starting", request_id)
    result = _request_enhancement(
        config=config,
        system_prompt=system_prompt,
        scene_definition=scene_definition,
        default_soundscape=default_soundscape,
        subject_roles=subject_roles,
        duration_seconds=duration_seconds,
        action_idea=clean_action,
        additional_notes=clean_notes,
    )
    _LOGGER.info("[H3 Prompt Enhancer] request %s complete", request_id)
    return dict(result)


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "MODEL_ENV",
    "TIMEOUT_ENV",
    "PromptEnhancerError",
    "compile_detailed_description",
    "get_enhancement",
    "load_enhancer_config",
    "max_beats_for_duration",
    "parse_enhancement_content",
]

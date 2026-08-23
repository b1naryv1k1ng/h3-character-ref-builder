"""OpenAI-compatible action enhancement with structured parsing and paid-call caching."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
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

MAX_RESPONSE_BYTES = 1024 * 1024
ENHANCEMENT_CACHE_SIZE = 128


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


_CACHE_LOCK = threading.Lock()
_ENHANCEMENT_CACHE: OrderedDict[str, tuple[str, str]] = OrderedDict()


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


def _response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "h3_action_enhancement",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "detailed_description": {"type": "string", "minLength": 1},
                    "additional_soundscape": {"type": "string"},
                },
                "required": ["detailed_description", "additional_soundscape"],
            },
        },
    }


def _request_payload(
    *,
    config: EnhancerConfig,
    system_prompt: str,
    scene_definition: str,
    duration_seconds: int,
    action_idea: str,
    additional_notes: str,
    structured: bool,
) -> dict[str, Any]:
    task = {
        "duration_seconds": duration_seconds,
        "action_idea": action_idea,
    }
    if scene_definition.strip():
        task["scene_definition"] = scene_definition.strip()
    if additional_notes.strip():
        task["additional_notes"] = additional_notes.strip()
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
        payload["response_format"] = _response_schema()
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
        raise PromptEnhancerError("Prompt enhancer provider response was unexpectedly large.")
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


def parse_enhancement_content(content: object) -> dict[str, str]:
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
    detailed = payload.get("detailed_description")
    additional = payload.get("additional_soundscape")
    if not isinstance(detailed, str) or not detailed.strip():
        raise PromptEnhancerError(
            "Prompt enhancer structured content has an invalid detailed_description."
        )
    if not detailed.strip().startswith("[Shot 1]"):
        raise PromptEnhancerError(
            "Prompt enhancer detailed_description must begin with [Shot 1]."
        )
    if not isinstance(additional, str):
        raise PromptEnhancerError(
            "Prompt enhancer structured content has an invalid additional_soundscape."
        )
    return {
        "detailed_description": detailed.strip(),
        "additional_soundscape": additional.strip(),
    }


def _request_enhancement(
    *,
    config: EnhancerConfig,
    system_prompt: str,
    scene_definition: str,
    duration_seconds: int,
    action_idea: str,
    additional_notes: str,
) -> dict[str, str]:
    strict_payload = _request_payload(
        config=config,
        system_prompt=system_prompt,
        scene_definition=scene_definition,
        duration_seconds=duration_seconds,
        action_idea=action_idea,
        additional_notes=additional_notes,
        structured=True,
    )
    try:
        response = _request_once(config, strict_payload)
    except _ProviderHTTPError as error:
        if error.status not in {400, 422}:
            _raise_http_failure(error)
        fallback_payload = _request_payload(
            config=config,
            system_prompt=system_prompt,
            scene_definition=scene_definition,
            duration_seconds=duration_seconds,
            action_idea=action_idea,
            additional_notes=additional_notes,
            structured=False,
        )
        try:
            response = _request_once(config, fallback_payload)
        except _ProviderHTTPError as fallback_error:
            _raise_http_failure(fallback_error)
    result = parse_enhancement_content(_message_content(response))
    if any(config.api_key in value for value in result.values()):
        raise PromptEnhancerError(
            "Prompt enhancer provider response contained sensitive credential data "
            "and was rejected."
        )
    return result


def _enhancement_cache_key(
    *,
    config: EnhancerConfig,
    system_prompt: str,
    scene_definition: str,
    duration_seconds: int,
    action_idea: str,
    additional_notes: str,
) -> str:
    relevant = {
        "endpoint": config.endpoint,
        "model": config.model,
        "system_prompt": system_prompt,
        "scene_definition": scene_definition,
        "duration_seconds": duration_seconds,
        "action_idea": action_idea,
        "additional_notes": additional_notes,
    }
    return hashlib.sha256(
        json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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
    scene_definition = str(character_context["scene_definition"]).strip()
    config = load_enhancer_config()
    cache_key = _enhancement_cache_key(
        config=config,
        system_prompt=system_prompt,
        scene_definition=scene_definition,
        duration_seconds=duration_seconds,
        action_idea=clean_action,
        additional_notes=clean_notes,
    )
    with _CACHE_LOCK:
        cached = _ENHANCEMENT_CACHE.get(cache_key)
        if cached is not None:
            _ENHANCEMENT_CACHE.move_to_end(cache_key)
            return {
                "detailed_description": cached[0],
                "additional_soundscape": cached[1],
            }
    result = _request_enhancement(
        config=config,
        system_prompt=system_prompt,
        scene_definition=scene_definition,
        duration_seconds=duration_seconds,
        action_idea=clean_action,
        additional_notes=clean_notes,
    )
    with _CACHE_LOCK:
        _ENHANCEMENT_CACHE[cache_key] = (
            result["detailed_description"],
            result["additional_soundscape"],
        )
        _ENHANCEMENT_CACHE.move_to_end(cache_key)
        while len(_ENHANCEMENT_CACHE) > ENHANCEMENT_CACHE_SIZE:
            _ENHANCEMENT_CACHE.popitem(last=False)
    return dict(result)


def enhancer_execution_fingerprint(
    *,
    character_context: str,
    duration_seconds: int,
    system_prompt: str,
    action_idea: str,
    additional_notes: str,
    non_diegetic_music: str,
) -> str:
    try:
        provider = get_default_provider_config_store().resolve()
    except ProviderConfigError as exc:
        raise PromptEnhancerError(str(exc)) from exc
    relevant = {
        "character_context": character_context,
        "duration_seconds": duration_seconds,
        "system_prompt": system_prompt,
        "action_idea": action_idea,
        "additional_notes": additional_notes,
        "non_diegetic_music": non_diegetic_music,
        "base_url": provider.base_url,
        "model": provider.model,
    }
    return hashlib.sha256(
        json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def clear_enhancement_cache() -> None:
    """Clear the in-process paid-call cache (primarily for tests and development)."""
    with _CACHE_LOCK:
        _ENHANCEMENT_CACHE.clear()


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "MODEL_ENV",
    "TIMEOUT_ENV",
    "PromptEnhancerError",
    "clear_enhancement_cache",
    "enhancer_execution_fingerprint",
    "get_enhancement",
    "load_enhancer_config",
    "parse_enhancement_content",
]

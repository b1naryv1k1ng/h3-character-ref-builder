"""Persistent, server-only provider configuration for H3 Prompt Enhancer."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .character_store import DATA_DIRECTORY

API_KEY_ENV = "H3_PROMPT_ENHANCER_API_KEY"
BASE_URL_ENV = "H3_PROMPT_ENHANCER_BASE_URL"
MODEL_ENV = "H3_PROMPT_ENHANCER_MODEL"
TIMEOUT_ENV = "H3_PROMPT_ENHANCER_TIMEOUT_SECONDS"

DEFAULT_BASE_URL = "https://api.venice.ai/api/v1"
DEFAULT_MODEL = "olafangensan-glm-4.7-flash-heretic"
DEFAULT_TIMEOUT_SECONDS = 60
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 300

CONFIG_FILENAME = "prompt-enhancer-config.json"
CONFIG_SCHEMA_VERSION = 1


class ProviderConfigError(RuntimeError):
    """Base class for safe, user-facing provider configuration failures."""


class InvalidProviderConfig(ProviderConfigError):
    """Configuration supplied by a caller is invalid."""


class ProviderConfigStorageError(ProviderConfigError):
    """Persistent configuration could not be read or written safely."""


@dataclass(frozen=True)
class ResolvedProviderConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: int
    api_key_source: str


def _normalize_base_url(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidProviderConfig("API Base URL must be text.")
    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise InvalidProviderConfig(
            "API Base URL must be a complete HTTP or HTTPS URL."
        )
    if parsed.query or parsed.fragment:
        raise InvalidProviderConfig(
            "API Base URL must not contain a query string or fragment."
        )
    if parsed.username is not None or parsed.password is not None:
        raise InvalidProviderConfig(
            "API Base URL must not contain embedded credentials."
        )
    return cleaned


def _normalize_model(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidProviderConfig("API Model must be non-empty text.")
    return value.strip()


def _normalize_timeout(value: object) -> int:
    if isinstance(value, bool):
        raise InvalidProviderConfig("Request Timeout must be an integer.")
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise InvalidProviderConfig("Request Timeout must be an integer.")
        try:
            value = int(raw)
        except ValueError as exc:
            raise InvalidProviderConfig(
                "Request Timeout must be an integer."
            ) from exc
    if not isinstance(value, int):
        raise InvalidProviderConfig("Request Timeout must be an integer.")
    if not MIN_TIMEOUT_SECONDS <= value <= MAX_TIMEOUT_SECONDS:
        raise InvalidProviderConfig(
            f"Request Timeout must be between {MIN_TIMEOUT_SECONDS} and "
            f"{MAX_TIMEOUT_SECONDS} seconds."
        )
    return value


class ProviderConfigStore:
    """Atomic JSON storage that reads fresh values for every operation."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.path = self.root / CONFIG_FILENAME
        self._lock = threading.RLock()

    @staticmethod
    def _validate_saved(data: object) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ProviderConfigStorageError(
                "H3 Prompt Enhancer configuration must be a JSON object."
            )
        allowed = {
            "schema_version",
            "base_url",
            "model",
            "timeout_seconds",
            "api_key",
        }
        if set(data) - allowed:
            raise ProviderConfigStorageError(
                "H3 Prompt Enhancer configuration contains unsupported fields."
            )
        if data.get("schema_version", CONFIG_SCHEMA_VERSION) != CONFIG_SCHEMA_VERSION:
            raise ProviderConfigStorageError(
                "H3 Prompt Enhancer configuration has an unsupported schema version."
            )
        try:
            result: dict[str, Any] = {
                "schema_version": CONFIG_SCHEMA_VERSION,
            }
            if "base_url" in data:
                result["base_url"] = _normalize_base_url(data["base_url"])
            if "model" in data:
                result["model"] = _normalize_model(data["model"])
            if "timeout_seconds" in data:
                result["timeout_seconds"] = _normalize_timeout(
                    data["timeout_seconds"]
                )
            if "api_key" in data:
                key = data["api_key"]
                if not isinstance(key, str) or not key.strip():
                    raise InvalidProviderConfig("Saved API key is invalid.")
                result["api_key"] = key.strip()
            return result
        except InvalidProviderConfig as exc:
            raise ProviderConfigStorageError(
                "H3 Prompt Enhancer configuration contains invalid values."
            ) from exc

    def read_saved(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"schema_version": CONFIG_SCHEMA_VERSION}
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ProviderConfigStorageError(
                    "H3 Prompt Enhancer configuration contains malformed JSON."
                ) from exc
            except OSError as exc:
                raise ProviderConfigStorageError(
                    "Could not read H3 Prompt Enhancer configuration."
                ) from exc
            return self._validate_saved(data)

    def _write_saved(self, data: dict[str, Any]) -> None:
        validated = self._validate_saved(data)
        temporary_name: str | None = None
        file_descriptor: int | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                try:
                    self.root.chmod(0o700)
                except OSError:
                    pass
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=".prompt-enhancer-", suffix=".tmp", dir=self.root
            )
            if os.name != "nt":
                os.fchmod(file_descriptor, 0o600)
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                file_descriptor = None
                json.dump(validated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
            temporary_name = None
        except OSError as exc:
            raise ProviderConfigStorageError(
                "Could not write H3 Prompt Enhancer configuration."
            ) from exc
        finally:
            if file_descriptor is not None:
                try:
                    os.close(file_descriptor)
                except OSError:
                    pass
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def update_provider(
        self, *, base_url: object, model: object, timeout_seconds: object
    ) -> dict[str, Any]:
        clean_base_url = _normalize_base_url(base_url)
        clean_model = _normalize_model(model)
        clean_timeout = _normalize_timeout(timeout_seconds)
        with self._lock:
            saved = self.read_saved()
            saved.update(
                {
                    "base_url": clean_base_url,
                    "model": clean_model,
                    "timeout_seconds": clean_timeout,
                }
            )
            self._write_saved(saved)
        return self.status()

    def set_api_key(self, api_key: object) -> dict[str, Any]:
        if not isinstance(api_key, str) or not api_key.strip():
            raise InvalidProviderConfig("API Key must not be empty.")
        with self._lock:
            saved = self.read_saved()
            saved["api_key"] = api_key.strip()
            self._write_saved(saved)
        return self.status()

    def clear_api_key(self) -> dict[str, Any]:
        with self._lock:
            saved = self.read_saved()
            saved.pop("api_key", None)
            self._write_saved(saved)
        return self.status()

    def resolve(self) -> ResolvedProviderConfig:
        saved = self.read_saved()
        saved_key = str(saved.get("api_key", "")).strip()
        environment_key = os.getenv(API_KEY_ENV, "").strip()
        if saved_key:
            api_key = saved_key
            api_key_source = "saved"
        elif environment_key:
            api_key = environment_key
            api_key_source = "environment"
        else:
            api_key = ""
            api_key_source = "none"

        base_url = saved.get("base_url")
        if base_url is None:
            base_url = os.getenv(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL
        model = saved.get("model")
        if model is None:
            model = os.getenv(MODEL_ENV, "").strip() or DEFAULT_MODEL
        timeout = saved.get("timeout_seconds")
        if timeout is None:
            timeout = os.getenv(TIMEOUT_ENV, "").strip() or DEFAULT_TIMEOUT_SECONDS

        return ResolvedProviderConfig(
            api_key=api_key,
            base_url=_normalize_base_url(base_url),
            model=_normalize_model(model),
            timeout_seconds=_normalize_timeout(timeout),
            api_key_source=api_key_source,
        )

    def status(self) -> dict[str, Any]:
        resolved = self.resolve()
        source_labels = {
            "saved": "Saved configuration",
            "environment": "Environment variable",
            "none": "Not configured",
        }
        return {
            "base_url": resolved.base_url,
            "model": resolved.model,
            "timeout_seconds": resolved.timeout_seconds,
            "api_key_configured": bool(resolved.api_key),
            "api_key_source": source_labels[resolved.api_key_source],
        }


_DEFAULT_STORES: dict[Path, ProviderConfigStore] = {}
_DEFAULT_STORES_LOCK = threading.Lock()


def get_default_provider_config_store() -> ProviderConfigStore:
    """Resolve provider configuration beneath ComfyUI's configured user directory."""
    import folder_paths

    root = (Path(folder_paths.get_user_directory()) / DATA_DIRECTORY).resolve()
    with _DEFAULT_STORES_LOCK:
        store = _DEFAULT_STORES.get(root)
        if store is None:
            store = ProviderConfigStore(root)
            _DEFAULT_STORES[root] = store
        return store


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "CONFIG_FILENAME",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_TIMEOUT_SECONDS",
    "MIN_TIMEOUT_SECONDS",
    "MODEL_ENV",
    "TIMEOUT_ENV",
    "InvalidProviderConfig",
    "ProviderConfigError",
    "ProviderConfigStorageError",
    "ProviderConfigStore",
    "ResolvedProviderConfig",
    "get_default_provider_config_store",
]

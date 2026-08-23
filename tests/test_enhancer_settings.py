from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from h3_character_ref_builder import enhancer_config as config_module
from h3_character_ref_builder import routes as route_module
from h3_character_ref_builder.enhancer_config import (
    API_KEY_ENV,
    BASE_URL_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    MODEL_ENV,
    TIMEOUT_ENV,
    InvalidProviderConfig,
    ProviderConfigStorageError,
    ProviderConfigStore,
)

from .test_v3_routes import install_app


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (API_KEY_ENV, BASE_URL_ENV, MODEL_ENV, TIMEOUT_ENV):
        monkeypatch.delenv(name, raising=False)


def test_defaults_and_environment_fallback_are_not_persisted(tmp_path, monkeypatch):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    resolved = store.resolve()
    assert resolved.base_url == DEFAULT_BASE_URL
    assert resolved.model == DEFAULT_MODEL
    assert resolved.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert resolved.api_key == ""
    assert store.status()["api_key_source"] == "Not configured"
    assert not store.path.exists()

    monkeypatch.setenv(API_KEY_ENV, " environment-secret ")
    monkeypatch.setenv(BASE_URL_ENV, "https://environment.example/v1")
    monkeypatch.setenv(MODEL_ENV, "environment-model")
    monkeypatch.setenv(TIMEOUT_ENV, "75")
    resolved = store.resolve()
    assert resolved.api_key == "environment-secret"
    assert resolved.base_url == "https://environment.example/v1"
    assert resolved.model == "environment-model"
    assert resolved.timeout_seconds == 75
    assert store.status()["api_key_source"] == "Environment variable"
    assert not store.path.exists()


def test_saved_values_override_environment_and_status_never_returns_key(
    tmp_path, monkeypatch
):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    monkeypatch.setenv(API_KEY_ENV, "environment-secret")
    monkeypatch.setenv(BASE_URL_ENV, "https://environment.example/v1")
    monkeypatch.setenv(MODEL_ENV, "environment-model")
    monkeypatch.setenv(TIMEOUT_ENV, "90")

    store.update_provider(
        base_url=" https://saved.example/v1/ ",
        model=" saved-model ",
        timeout_seconds=42,
    )
    store.set_api_key(" saved-secret ")
    resolved = store.resolve()
    assert resolved.base_url == "https://saved.example/v1"
    assert resolved.model == "saved-model"
    assert resolved.timeout_seconds == 42
    assert resolved.api_key == "saved-secret"
    assert resolved.api_key_source == "saved"

    serialized_status = json.dumps(store.status())
    assert "saved-secret" not in serialized_status
    assert "environment-secret" not in serialized_status
    assert "api_key\"" not in serialized_status
    assert store.status() == {
        "base_url": "https://saved.example/v1",
        "model": "saved-model",
        "timeout_seconds": 42,
        "api_key_configured": True,
        "api_key_source": "Saved configuration",
    }


def test_replacing_and_clearing_saved_api_key_uses_environment_fallback(
    tmp_path, monkeypatch
):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    monkeypatch.setenv(API_KEY_ENV, "environment-secret")
    store.set_api_key("first-secret")
    store.set_api_key("replacement-secret")
    assert store.read_saved()["api_key"] == "replacement-secret"
    assert "first-secret" not in store.path.read_text(encoding="utf-8")

    status = store.clear_api_key()
    assert "api_key" not in store.read_saved()
    assert status["api_key_configured"] is True
    assert status["api_key_source"] == "Environment variable"
    assert "environment-secret" not in store.path.read_text(encoding="utf-8")


def test_persistence_is_atomic_and_failed_replace_preserves_previous_file(
    tmp_path, monkeypatch
):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    store.update_provider(
        base_url="https://provider.example/v1",
        model="initial-model",
        timeout_seconds=60,
    )
    original = store.path.read_bytes()

    def fail_replace(source, destination):
        del source, destination
        raise OSError("simulated replace failure")

    monkeypatch.setattr(config_module.os, "replace", fail_replace)
    with pytest.raises(ProviderConfigStorageError, match="Could not write"):
        store.set_api_key("never-written-secret")

    assert store.path.read_bytes() == original
    assert not list(store.root.glob(".prompt-enhancer-*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are unavailable")
def test_saved_configuration_uses_restrictive_permissions_on_posix():
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        store = ProviderConfigStore(Path(directory) / "h3-character-ref-builder")
        store.set_api_key("secret")
        assert store.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "contents",
    [
        "not-json secret-must-not-leak",
        "[]",
        '{"schema_version": 99}',
        '{"api_key": 42}',
        '{"unexpected": "secret-must-not-leak"}',
    ],
)
def test_malformed_configuration_fails_clearly_without_leaking_contents(
    tmp_path, contents
):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    store.root.mkdir(parents=True)
    store.path.write_text(contents, encoding="utf-8")
    with pytest.raises(ProviderConfigStorageError) as error:
        store.resolve()
    assert "secret-must-not-leak" not in str(error.value)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"base_url": "not-a-url", "model": "model", "timeout_seconds": 60},
            "complete HTTP",
        ),
        (
            {
                "base_url": "https://provider.example/v1",
                "model": " ",
                "timeout_seconds": 60,
            },
            "API Model",
        ),
        (
            {
                "base_url": "https://provider.example/v1",
                "model": "model",
                "timeout_seconds": 0,
            },
            "between 1 and 300",
        ),
    ],
)
def test_invalid_provider_values_are_rejected(tmp_path, kwargs, message):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    with pytest.raises(InvalidProviderConfig, match=message):
        store.update_provider(**kwargs)
    assert not store.path.exists()


def test_configuration_routes_are_write_only_for_api_key(tmp_path, monkeypatch):
    store = ProviderConfigStore(tmp_path / "h3-character-ref-builder")
    monkeypatch.setattr(
        route_module, "get_default_provider_config_store", lambda: store
    )
    app = install_app(tmp_path, monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            initial = await client.get(
                "/api/h3-character-ref-builder/prompt-enhancer/config"
            )
            initial_payload = await initial.json()
            assert initial.status == 200
            assert initial_payload["data"]["base_url"] == DEFAULT_BASE_URL
            assert "api_key" not in initial_payload["data"]

            provider = await client.put(
                "/api/h3-character-ref-builder/prompt-enhancer/config",
                json={
                    "base_url": "https://saved.example/v1",
                    "model": "saved-model",
                    "timeout_seconds": 33,
                },
            )
            assert provider.status == 200
            assert (await provider.json())["data"]["model"] == "saved-model"

            secret = "route-secret-never-return"
            saved = await client.put(
                "/api/h3-character-ref-builder/prompt-enhancer/api-key",
                json={"api_key": secret},
            )
            saved_text = await saved.text()
            assert saved.status == 200
            assert secret not in saved_text
            assert json.loads(saved_text)["data"]["api_key_configured"] is True
            assert store.read_saved()["api_key"] == secret

            replaced = await client.put(
                "/api/h3-character-ref-builder/prompt-enhancer/api-key",
                json={"api_key": "replacement-secret"},
            )
            assert "replacement-secret" not in await replaced.text()
            assert store.read_saved()["api_key"] == "replacement-secret"

            status = await client.get(
                "/api/h3-character-ref-builder/prompt-enhancer/config"
            )
            status_text = await status.text()
            assert "replacement-secret" not in status_text
            assert "api_key\"" not in status_text

            cleared = await client.delete(
                "/api/h3-character-ref-builder/prompt-enhancer/api-key"
            )
            cleared_text = await cleared.text()
            assert cleared.status == 200
            assert "replacement-secret" not in cleared_text
            assert json.loads(cleared_text)["data"]["api_key_configured"] is False
            assert "api_key" not in store.read_saved()

    asyncio.run(scenario())


def test_frontend_registers_native_write_only_settings_once():
    source = (
        Path(__file__).parents[1] / "web" / "prompt_enhancer_settings.js"
    ).read_text(encoding="utf-8")

    assert source.count("app.registerExtension({") == 1
    assert source.count("H3.CharacterRefBuilder.PromptEnhancer.") == 4
    assert 'const SETTINGS_CATEGORY = "H3 Character Ref Builder"' in source
    assert 'controlInput("password")' in source
    assert 'input.autocomplete = "new-password"' in source
    assert 'input.value = ""' in source
    assert 'Object.hasOwn(data, "api_key")' in source
    assert "status.api_key =" not in source
    assert 'requestJson("/api-key", {' in source
    assert 'method: "DELETE"' in source
    assert 'method: "PUT"' in source

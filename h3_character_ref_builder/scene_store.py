"""Filesystem-backed reusable Scene Preset storage."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from .character_store import DATA_DIRECTORY

SCENE_SCHEMA_VERSION = 2
LEGACY_SCENE_SCHEMA_VERSION = 1
_SUBJECT_2_PREFIX = re.compile(r"^\s*<Subject\s+2>\s+is\s*", re.IGNORECASE)


class SceneStoreError(RuntimeError):
    """Base error for expected scene-storage failures."""


class InvalidSceneId(SceneStoreError):
    pass


class SceneNotFound(SceneStoreError):
    pass


class SceneCorrupt(SceneStoreError):
    pass


class DuplicateSceneName(SceneStoreError):
    pass


class InvalidScene(SceneStoreError):
    pass


def validate_scene_id(scene_id: str) -> str:
    if not isinstance(scene_id, str):
        raise InvalidSceneId("Scene preset UUID must be a string.")
    try:
        canonical = str(uuid.UUID(scene_id))
    except (ValueError, AttributeError) as exc:
        raise InvalidSceneId(f"Invalid scene preset UUID: {scene_id!r}.") from exc
    if scene_id.lower() != canonical:
        raise InvalidSceneId(f"Invalid scene preset UUID: {scene_id!r}.")
    return canonical


def normalize_scene_definition(definition: Any) -> str:
    if not isinstance(definition, str):
        raise InvalidScene("Scene definition must be a string.")
    body = _SUBJECT_2_PREFIX.sub("", definition, count=1).strip()
    if len(body) > 50_000:
        raise InvalidScene("Scene definition must be 50,000 characters or fewer.")
    return body


def normalize_default_soundscape(soundscape: Any) -> str:
    if not isinstance(soundscape, str):
        raise InvalidScene("Default soundscape must be a string.")
    body = soundscape.strip()
    if len(body) > 50_000:
        raise InvalidScene("Default soundscape must be 50,000 characters or fewer.")
    return body


class SceneStore:
    """Manage independent UUID-addressed scene presets beneath one trusted root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.scenes_root = self.root / "scenes"
        self.scenes_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _scene_dir(self, scene_id: str) -> Path:
        canonical = validate_scene_id(scene_id)
        candidate = (self.scenes_root / canonical).resolve()
        if candidate.parent != self.scenes_root.resolve():
            raise InvalidSceneId("Scene id escapes the managed scene directory.")
        return candidate

    def _scene_path(self, scene_id: str) -> Path:
        return self._scene_dir(scene_id) / "scene.json"

    @staticmethod
    def _validate_text(
        name: Any, definition: Any, default_soundscape: Any
    ) -> tuple[str, str, str]:
        if not isinstance(name, str):
            raise InvalidScene("Scene name must be a string.")
        clean_name = name.strip()
        if not clean_name:
            raise InvalidScene("Scene name is required.")
        if len(clean_name) > 200:
            raise InvalidScene("Scene name must be 200 characters or fewer.")
        return (
            clean_name,
            normalize_scene_definition(definition),
            normalize_default_soundscape(default_soundscape),
        )

    @classmethod
    def _validate_scene_data(cls, data: Any, expected_id: str) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "id",
            "name",
            "definition",
            "default_soundscape",
        }:
            raise SceneCorrupt(f"Scene preset {expected_id} has invalid fields.")
        if data["schema_version"] != SCENE_SCHEMA_VERSION or data["id"] != expected_id:
            raise SceneCorrupt(f"Scene preset {expected_id} has invalid identity data.")
        try:
            name, definition, default_soundscape = cls._validate_text(
                data["name"], data["definition"], data["default_soundscape"]
            )
        except InvalidScene as exc:
            raise SceneCorrupt(f"Scene preset {expected_id} is invalid: {exc}") from exc
        return {
            "schema_version": SCENE_SCHEMA_VERSION,
            "id": expected_id,
            "name": name,
            "definition": definition,
            "default_soundscape": default_soundscape,
        }

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".scene-", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def _migrate_v1(self, scene_id: str, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "id",
            "name",
            "definition",
        }:
            raise SceneCorrupt(f"Scene preset {scene_id} has invalid V1 fields.")
        if (
            data["schema_version"] != LEGACY_SCENE_SCHEMA_VERSION
            or data["id"] != scene_id
        ):
            raise SceneCorrupt(f"Scene preset {scene_id} has invalid V1 identity data.")
        migrated = {
            "schema_version": SCENE_SCHEMA_VERSION,
            "id": scene_id,
            "name": data["name"],
            "definition": data["definition"],
            "default_soundscape": "",
        }
        migrated = self._validate_scene_data(migrated, scene_id)
        self._atomic_write(self._scene_path(scene_id), migrated)
        return migrated

    def _read_unlocked(self, scene_id: str) -> dict[str, Any]:
        canonical = validate_scene_id(scene_id)
        path = self._scene_path(canonical)
        if not path.is_file():
            raise SceneNotFound(f"Scene preset {canonical} no longer exists.")
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise SceneCorrupt(f"Scene preset {canonical} is malformed.") from exc
        if (
            isinstance(data, dict)
            and data.get("schema_version") == LEGACY_SCENE_SCHEMA_VERSION
        ):
            data = self._migrate_v1(canonical, data)
        return self._validate_scene_data(data, canonical)

    def _assert_unique_name(self, name: str, exclude_id: str | None = None) -> None:
        folded = name.casefold()
        for scene in self.list_scenes():
            if scene["id"] != exclude_id and scene["name"].casefold() == folded:
                raise DuplicateSceneName(
                    f'A scene preset named "{name}" already exists (names are case-insensitive).'
                )

    def create_scene(
        self,
        name: str,
        definition: str = "",
        default_soundscape: str = "",
    ) -> dict[str, Any]:
        clean_name, clean_definition, clean_soundscape = self._validate_text(
            name, definition, default_soundscape
        )
        with self._lock:
            self._assert_unique_name(clean_name)
            scene_id = str(uuid.uuid4())
            directory = self._scene_dir(scene_id)
            directory.mkdir(parents=False, exist_ok=False)
            scene = {
                "schema_version": SCENE_SCHEMA_VERSION,
                "id": scene_id,
                "name": clean_name,
                "definition": clean_definition,
                "default_soundscape": clean_soundscape,
            }
            try:
                self._atomic_write(directory / "scene.json", scene)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return copy.deepcopy(scene)

    def list_scenes(self) -> list[dict[str, str]]:
        scenes: list[dict[str, str]] = []
        with self._lock:
            for directory in self.scenes_root.iterdir():
                if not directory.is_dir():
                    continue
                try:
                    scene = self._read_unlocked(directory.name)
                except SceneStoreError:
                    continue
                scenes.append({"id": scene["id"], "name": scene["name"]})
        return sorted(scenes, key=lambda item: (item["name"].casefold(), item["name"]))

    def get_scene(self, scene_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._read_unlocked(scene_id))

    def update_scene(
        self,
        scene_id: str,
        *,
        name: str | None = None,
        definition: str | None = None,
        default_soundscape: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_scene_id(scene_id)
        with self._lock:
            scene = self._read_unlocked(canonical)
            clean_name, clean_definition, clean_soundscape = self._validate_text(
                scene["name"] if name is None else name,
                scene["definition"] if definition is None else definition,
                scene["default_soundscape"]
                if default_soundscape is None
                else default_soundscape,
            )
            self._assert_unique_name(clean_name, exclude_id=canonical)
            scene["name"] = clean_name
            scene["definition"] = clean_definition
            scene["default_soundscape"] = clean_soundscape
            self._atomic_write(self._scene_path(canonical), scene)
            return copy.deepcopy(scene)

    def delete_scene(self, scene_id: str) -> None:
        canonical = validate_scene_id(scene_id)
        with self._lock:
            directory = self._scene_dir(canonical)
            if not (directory / "scene.json").is_file():
                raise SceneNotFound(f"Scene preset {canonical} no longer exists.")
            shutil.rmtree(directory)

    def prompt_fingerprint(self, scene_id: str) -> str:
        """Return prompt-relevant scene state, deliberately excluding its name."""
        scene = self.get_scene(scene_id)
        return f"{scene['id']}\0{scene['definition']}\0{scene['default_soundscape']}"


_DEFAULT_STORES: dict[Path, SceneStore] = {}
_DEFAULT_STORES_LOCK = threading.Lock()


def get_default_scene_store() -> SceneStore:
    import folder_paths

    root = (Path(folder_paths.get_user_directory()) / DATA_DIRECTORY).resolve()
    with _DEFAULT_STORES_LOCK:
        store = _DEFAULT_STORES.get(root)
        if store is None:
            store = SceneStore(root)
            _DEFAULT_STORES[root] = store
        return store

"""Filesystem-backed character profile storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from .media import MEDIA_SLOTS, extension_for_upload, validate_media_file

SCHEMA_VERSION = 1
DATA_DIRECTORY = "h3-character-ref-builder"


class CharacterStoreError(RuntimeError):
    """Base error for expected storage and validation failures."""


class InvalidCharacterId(CharacterStoreError):
    pass


class ProfileNotFound(CharacterStoreError):
    pass


class ProfileCorrupt(CharacterStoreError):
    pass


class DuplicateCharacterName(CharacterStoreError):
    pass


class InvalidProfile(CharacterStoreError):
    pass


class MissingMedia(CharacterStoreError):
    pass


def validate_character_id(character_id: str) -> str:
    """Return a canonical UUID or reject the value before any path use."""
    if not isinstance(character_id, str):
        raise InvalidCharacterId("Character id must be a UUID string.")
    try:
        canonical = str(uuid.UUID(character_id))
    except (ValueError, AttributeError) as exc:
        raise InvalidCharacterId(f"Invalid character profile UUID: {character_id!r}.") from exc
    if character_id.lower() != canonical:
        raise InvalidCharacterId(f"Invalid character profile UUID: {character_id!r}.")
    return canonical


class CharacterStore:
    """Manage versioned profile JSON and media beneath a single trusted root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.characters_root = self.root / "characters"
        self.characters_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _character_dir(self, character_id: str) -> Path:
        canonical = validate_character_id(character_id)
        candidate = (self.characters_root / canonical).resolve()
        if candidate.parent != self.characters_root.resolve():
            raise InvalidCharacterId("Character id escapes the managed character directory.")
        return candidate

    def _profile_path(self, character_id: str) -> Path:
        return self._character_dir(character_id) / "profile.json"

    @staticmethod
    def _validate_text(name: Any, description: Any) -> tuple[str, str]:
        if not isinstance(name, str):
            raise InvalidProfile("Character name must be a string.")
        clean_name = name.strip()
        if not clean_name:
            raise InvalidProfile("Character name is required.")
        if len(clean_name) > 200:
            raise InvalidProfile("Character name must be 200 characters or fewer.")
        if not isinstance(description, str):
            raise InvalidProfile("Character description must be a string.")
        if len(description) > 20_000:
            raise InvalidProfile("Character description must be 20,000 characters or fewer.")
        return clean_name, description

    @staticmethod
    def _validate_profile_data(data: Any, expected_id: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ProfileCorrupt(f"Character profile {expected_id} is not a JSON object.")
        required = {
            "schema_version",
            "id",
            "name",
            "description",
            *MEDIA_SLOTS,
        }
        if set(data) != required:
            raise ProfileCorrupt(
                f"Character profile {expected_id} has an invalid set of fields."
            )
        if data["schema_version"] != SCHEMA_VERSION:
            raise ProfileCorrupt(
                f"Character profile {expected_id} uses unsupported schema version "
                f"{data['schema_version']!r}."
            )
        if data["id"] != expected_id:
            raise ProfileCorrupt(f"Character profile {expected_id} contains a mismatched id.")
        try:
            clean_name, description = CharacterStore._validate_text(
                data["name"], data["description"]
            )
        except InvalidProfile as exc:
            raise ProfileCorrupt(f"Character profile {expected_id} is invalid: {exc}") from exc
        data = dict(data)
        data["name"] = clean_name
        data["description"] = description
        for slot in MEDIA_SLOTS:
            filename = data[slot]
            if filename is not None:
                if not isinstance(filename, str) or Path(filename).name != filename:
                    raise ProfileCorrupt(
                        f"Character profile {expected_id} has an unsafe {slot} filename."
                    )
                if not filename.startswith(f"{slot}."):
                    raise ProfileCorrupt(
                        f"Character profile {expected_id} has an invalid {slot} filename."
                    )
        return data

    def _read_profile(self, character_id: str) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        path = self._profile_path(canonical)
        if not path.is_file():
            raise ProfileNotFound(f"Character profile {canonical} no longer exists.")
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileCorrupt(f"Character profile {canonical} is malformed.") from exc
        return self._validate_profile_data(data, canonical)

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".profile-", suffix=".tmp", dir=path.parent
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

    def _assert_unique_name(self, name: str, exclude_id: str | None = None) -> None:
        folded = name.casefold()
        for profile in self.list_profiles():
            if profile["id"] != exclude_id and profile["name"].casefold() == folded:
                raise DuplicateCharacterName(
                    f'A character named "{name}" already exists (names are case-insensitive).'
                )

    def create_profile(self, name: str, description: str = "") -> dict[str, Any]:
        clean_name, description = self._validate_text(name, description)
        with self._lock:
            self._assert_unique_name(clean_name)
            character_id = str(uuid.uuid4())
            directory = self._character_dir(character_id)
            directory.mkdir(parents=False, exist_ok=False)
            profile = {
                "schema_version": SCHEMA_VERSION,
                "id": character_id,
                "name": clean_name,
                "description": description,
                "reference_image_1": None,
                "reference_image_2": None,
                "reference_audio": None,
            }
            try:
                self._atomic_write_json(directory / "profile.json", profile)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return dict(profile)

    def list_profiles(self) -> list[dict[str, str]]:
        profiles: list[dict[str, str]] = []
        if not self.characters_root.exists():
            return profiles
        for directory in self.characters_root.iterdir():
            if not directory.is_dir():
                continue
            try:
                profile = self._read_profile(directory.name)
            except CharacterStoreError:
                continue
            profiles.append({"id": profile["id"], "name": profile["name"]})
        return sorted(profiles, key=lambda item: (item["name"].casefold(), item["name"]))

    def get_profile(self, character_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._read_profile(character_id))

    def update_profile(
        self,
        character_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile(canonical)
            new_name = profile["name"] if name is None else name
            new_description = profile["description"] if description is None else description
            clean_name, clean_description = self._validate_text(new_name, new_description)
            self._assert_unique_name(clean_name, exclude_id=canonical)
            profile["name"] = clean_name
            profile["description"] = clean_description
            self._atomic_write_json(self._profile_path(canonical), profile)
            return dict(profile)

    def delete_profile(self, character_id: str) -> None:
        canonical = validate_character_id(character_id)
        with self._lock:
            directory = self._character_dir(canonical)
            if not (directory / "profile.json").is_file():
                raise ProfileNotFound(f"Character profile {canonical} no longer exists.")
            shutil.rmtree(directory)

    def replace_media(
        self,
        character_id: str,
        slot: str,
        source: BinaryIO,
        original_filename: str,
        *,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if slot not in MEDIA_SLOTS:
            raise InvalidProfile(f"Invalid media slot: {slot!r}.")
        canonical = validate_character_id(character_id)
        extension = extension_for_upload(slot, original_filename, content_type)
        with self._lock:
            profile = self._read_profile(canonical)
            directory = self._character_dir(canonical)
            destination = directory / f"{slot}{extension}"
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{slot}-", suffix=".upload", dir=directory
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    shutil.copyfileobj(source, handle, length=1024 * 1024)
                    handle.flush()
                    os.fsync(handle.fileno())
                validate_media_file(slot, Path(temporary_name), extension)
                os.replace(temporary_name, destination)
                profile[slot] = destination.name
                self._atomic_write_json(directory / "profile.json", profile)
                for candidate in directory.glob(f"{slot}.*"):
                    if candidate != destination and candidate.is_file():
                        candidate.unlink()
            except Exception:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                raise
            return dict(profile)

    def media_path(self, character_id: str, slot: str) -> Path:
        if slot not in MEDIA_SLOTS:
            raise InvalidProfile(f"Invalid media slot: {slot!r}.")
        profile = self._read_profile(character_id)
        filename = profile[slot]
        if not filename:
            raise MissingMedia(
                f'Character "{profile["name"]}" is missing required media slot {slot}.'
            )
        directory = self._character_dir(profile["id"])
        candidate = (directory / filename).resolve()
        if candidate.parent != directory.resolve():
            raise ProfileCorrupt(
                f"Character profile {profile['id']} contains an unsafe media path."
            )
        if not candidate.is_file():
            raise MissingMedia(
                f'Character "{profile["name"]}" is missing required media slot {slot}.'
            )
        return candidate

    def fingerprint(self, character_id: str) -> str:
        """Hash only the selected profile JSON and its three managed assets."""
        with self._lock:
            return self._fingerprint_unlocked(character_id)

    def _fingerprint_unlocked(self, character_id: str) -> str:
        canonical = validate_character_id(character_id)
        self._read_profile(canonical)
        digest = hashlib.sha256()
        profile_path = self._profile_path(canonical)
        digest.update(profile_path.read_bytes())
        for slot in MEDIA_SLOTS:
            path = self.media_path(canonical, slot)
            digest.update(slot.encode("utf-8"))
            digest.update(path.name.encode("utf-8"))
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()


_DEFAULT_STORES: dict[Path, CharacterStore] = {}
_DEFAULT_STORES_LOCK = threading.Lock()


def get_default_store() -> CharacterStore:
    """Resolve persistent storage through ComfyUI's configured user directory."""
    import folder_paths

    root = (Path(folder_paths.get_user_directory()) / DATA_DIRECTORY).resolve()
    with _DEFAULT_STORES_LOCK:
        store = _DEFAULT_STORES.get(root)
        if store is None:
            store = CharacterStore(root)
            _DEFAULT_STORES[root] = store
        return store

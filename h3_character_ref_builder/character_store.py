"""Filesystem-backed character profile and reference-library storage."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from .media import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MEDIA_SLOTS,
    extension_for_upload,
    validate_media_file,
)

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
DATA_DIRECTORY = "h3-character-ref-builder"
MEDIA_LIMITS = {"image": 9, "audio": 3}
MEDIA_COLLECTIONS = {"image": "images", "audio": "audio"}
DEFAULT_SLOTS = ("image_1", "image_2", "audio")
_UNSET = object()


class CharacterStoreError(RuntimeError):
    """Base error for expected storage and validation failures."""


class InvalidCharacterId(CharacterStoreError):
    pass


class InvalidMediaId(CharacterStoreError):
    pass


class ProfileNotFound(CharacterStoreError):
    pass


class MediaNotFound(CharacterStoreError):
    pass


class ProfileCorrupt(CharacterStoreError):
    pass


class DuplicateCharacterName(CharacterStoreError):
    pass


class InvalidProfile(CharacterStoreError):
    pass


class MediaLimitReached(CharacterStoreError):
    pass


class MissingMedia(CharacterStoreError):
    pass


def _validate_uuid(
    value: str, description: str, error_type: type[CharacterStoreError]
) -> str:
    if not isinstance(value, str):
        raise error_type(f"{description} must be a UUID string.")
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise error_type(f"Invalid {description.lower()}: {value!r}.") from exc
    if value.lower() != canonical:
        raise error_type(f"Invalid {description.lower()}: {value!r}.")
    return canonical


def validate_character_id(character_id: str) -> str:
    return _validate_uuid(character_id, "Character profile UUID", InvalidCharacterId)


def validate_media_id(media_id: str) -> str:
    return _validate_uuid(media_id, "Media UUID", InvalidMediaId)


class CharacterStore:
    """Manage versioned profiles and UUID-addressed media beneath one trusted root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.characters_root = self.root / "characters"
        self.characters_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _character_dir(self, character_id: str) -> Path:
        canonical = validate_character_id(character_id)
        candidate = (self.characters_root / canonical).resolve()
        if candidate.parent != self.characters_root.resolve():
            raise InvalidCharacterId(
                "Character id escapes the managed character directory."
            )
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
            raise InvalidProfile(
                "Character description must be 20,000 characters or fewer."
            )
        return clean_name, description

    @staticmethod
    def _validate_label(label: Any) -> str:
        if not isinstance(label, str):
            raise InvalidProfile("Media label must be a string.")
        clean_label = label.strip()
        if len(clean_label) > 200:
            raise InvalidProfile("Media label must be 200 characters or fewer.")
        return clean_label

    @staticmethod
    def _validate_media_type(media_type: Any) -> str:
        if media_type not in MEDIA_LIMITS:
            raise InvalidProfile("Media type must be either 'image' or 'audio'.")
        return media_type

    @staticmethod
    def _validate_record(
        record: Any, media_type: str, expected_id: str
    ) -> dict[str, str]:
        if not isinstance(record, dict) or set(record) != {"id", "file", "label"}:
            raise ProfileCorrupt(
                f"Character profile {expected_id} contains an invalid {media_type} record."
            )
        try:
            media_id = validate_media_id(record["id"])
            label = CharacterStore._validate_label(record["label"])
        except CharacterStoreError as exc:
            raise ProfileCorrupt(
                f"Character profile {expected_id} is invalid: {exc}"
            ) from exc
        file_value = record["file"]
        if not isinstance(file_value, str):
            raise ProfileCorrupt(
                f"Character profile {expected_id} contains an invalid media filename."
            )
        path = Path(file_value)
        collection = MEDIA_COLLECTIONS[media_type]
        allowed_extensions = (
            IMAGE_EXTENSIONS if media_type == "image" else AUDIO_EXTENSIONS
        )
        if (
            path.is_absolute()
            or len(path.parts) != 2
            or path.parts[0] != collection
            or Path(path.parts[1]).stem != media_id
            or Path(path.parts[1]).suffix.lower() not in allowed_extensions
        ):
            raise ProfileCorrupt(
                f"Character profile {expected_id} contains an unsafe {media_type} filename."
            )
        return {"id": media_id, "file": path.as_posix(), "label": label}

    @staticmethod
    def _validate_profile_data(data: Any, expected_id: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ProfileCorrupt(
                f"Character profile {expected_id} is not a JSON object."
            )
        required = {
            "schema_version",
            "id",
            "name",
            "description",
            "images",
            "audio",
            "defaults",
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
            raise ProfileCorrupt(
                f"Character profile {expected_id} contains a mismatched id."
            )
        try:
            clean_name, description = CharacterStore._validate_text(
                data["name"], data["description"]
            )
        except InvalidProfile as exc:
            raise ProfileCorrupt(
                f"Character profile {expected_id} is invalid: {exc}"
            ) from exc

        if not isinstance(data["images"], list) or not isinstance(data["audio"], list):
            raise ProfileCorrupt(
                f"Character profile {expected_id} media collections must be arrays."
            )
        if len(data["images"]) > MEDIA_LIMITS["image"]:
            raise ProfileCorrupt(
                f"Character profile {expected_id} has too many images."
            )
        if len(data["audio"]) > MEDIA_LIMITS["audio"]:
            raise ProfileCorrupt(
                f"Character profile {expected_id} has too many audio references."
            )

        images = [
            CharacterStore._validate_record(record, "image", expected_id)
            for record in data["images"]
        ]
        audio = [
            CharacterStore._validate_record(record, "audio", expected_id)
            for record in data["audio"]
        ]
        all_ids = [record["id"] for record in [*images, *audio]]
        if len(all_ids) != len(set(all_ids)):
            raise ProfileCorrupt(
                f"Character profile {expected_id} contains duplicate media IDs."
            )

        defaults = data["defaults"]
        if not isinstance(defaults, dict) or set(defaults) != set(DEFAULT_SLOTS):
            raise ProfileCorrupt(
                f"Character profile {expected_id} has invalid defaults."
            )
        image_ids = {record["id"] for record in images}
        audio_ids = {record["id"] for record in audio}
        clean_defaults: dict[str, str | None] = {}
        for slot in DEFAULT_SLOTS:
            value = defaults[slot]
            if value is not None:
                try:
                    value = validate_media_id(value)
                except InvalidMediaId as exc:
                    raise ProfileCorrupt(
                        f"Character profile {expected_id} has an invalid {slot} default."
                    ) from exc
                valid_ids = audio_ids if slot == "audio" else image_ids
                if value not in valid_ids:
                    raise ProfileCorrupt(
                        f"Character profile {expected_id} default {slot} references "
                        "missing or incorrect media."
                    )
            clean_defaults[slot] = value
        if (
            clean_defaults["image_1"] is not None
            and clean_defaults["image_1"] == clean_defaults["image_2"]
        ):
            raise ProfileCorrupt(
                f"Character profile {expected_id} selects the same image twice."
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "id": expected_id,
            "name": clean_name,
            "description": description,
            "images": images,
            "audio": audio,
            "defaults": clean_defaults,
        }

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

    @staticmethod
    def _copy_file_atomically(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}-", suffix=".migration", dir=destination.parent
        )
        try:
            with (
                source.open("rb") as source_handle,
                os.fdopen(fd, "wb") as target_handle,
            ):
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                target_handle.flush()
                os.fsync(target_handle.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def _migrate_v1(self, character_id: str, data: dict[str, Any]) -> dict[str, Any]:
        required = {
            "schema_version",
            "id",
            "name",
            "description",
            *MEDIA_SLOTS,
        }
        if set(data) != required or data.get("schema_version") != LEGACY_SCHEMA_VERSION:
            raise ProfileCorrupt(
                f"Character profile {character_id} has invalid V1 data."
            )
        if data.get("id") != character_id:
            raise ProfileCorrupt(
                f"Character profile {character_id} contains a mismatched id."
            )
        try:
            name, description = self._validate_text(data["name"], data["description"])
        except InvalidProfile as exc:
            raise ProfileCorrupt(
                f"Character profile {character_id} is invalid: {exc}"
            ) from exc

        directory = self._character_dir(character_id)
        profile = {
            "schema_version": SCHEMA_VERSION,
            "id": character_id,
            "name": name,
            "description": description,
            "images": [],
            "audio": [],
            "defaults": {"image_1": None, "image_2": None, "audio": None},
        }
        slot_config = {
            "reference_image_1": ("image", "image_1", "Reference Image 1"),
            "reference_image_2": ("image", "image_2", "Reference Image 2"),
            "reference_audio": ("audio", "audio", "Reference Audio"),
        }
        copied: list[Path] = []
        legacy_sources: list[Path] = []
        try:
            for slot in MEDIA_SLOTS:
                filename = data[slot]
                if filename is None:
                    continue
                if (
                    not isinstance(filename, str)
                    or Path(filename).name != filename
                    or not filename.startswith(f"{slot}.")
                ):
                    raise ProfileCorrupt(
                        f"Character profile {character_id} has an unsafe legacy {slot} filename."
                    )
                source = (directory / filename).resolve()
                if source.parent != directory.resolve():
                    raise ProfileCorrupt(
                        f"Character profile {character_id} has an unsafe legacy media path."
                    )
                if not source.is_file():
                    raise MissingMedia(
                        f'Character "{name}" is missing required legacy media slot {slot}.'
                    )
                media_type, default_slot, label = slot_config[slot]
                extension = extension_for_upload(media_type, filename)
                media_id = str(uuid.uuid5(uuid.UUID(character_id), f"h3-v1:{slot}"))
                relative = (
                    Path(MEDIA_COLLECTIONS[media_type]) / f"{media_id}{extension}"
                )
                destination = directory / relative
                self._copy_file_atomically(source, destination)
                validate_media_file(media_type, destination, extension)
                copied.append(destination)
                legacy_sources.append(source)
                profile[MEDIA_COLLECTIONS[media_type]].append(
                    {"id": media_id, "file": relative.as_posix(), "label": label}
                )
                profile["defaults"][default_slot] = media_id

            profile = self._validate_profile_data(profile, character_id)
            self._atomic_write_json(directory / "profile.json", profile)
        except Exception:
            for path in copied:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            raise

        for source in legacy_sources:
            try:
                source.unlink()
            except FileNotFoundError:
                pass
        return profile

    def _read_profile_unlocked(self, character_id: str) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        path = self._profile_path(canonical)
        if not path.is_file():
            raise ProfileNotFound(f"Character profile {canonical} no longer exists.")
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileCorrupt(
                f"Character profile {canonical} is malformed."
            ) from exc
        if (
            isinstance(data, dict)
            and data.get("schema_version") == LEGACY_SCHEMA_VERSION
        ):
            data = self._migrate_v1(canonical, data)
        return self._validate_profile_data(data, canonical)

    def _read_profile(self, character_id: str) -> dict[str, Any]:
        with self._lock:
            return self._read_profile_unlocked(character_id)

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
                "images": [],
                "audio": [],
                "defaults": {"image_1": None, "image_2": None, "audio": None},
            }
            try:
                self._atomic_write_json(directory / "profile.json", profile)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return copy.deepcopy(profile)

    def list_profiles(self) -> list[dict[str, str]]:
        profiles: list[dict[str, str]] = []
        with self._lock:
            if not self.characters_root.exists():
                return profiles
            for directory in self.characters_root.iterdir():
                if not directory.is_dir():
                    continue
                try:
                    profile = self._read_profile_unlocked(directory.name)
                except CharacterStoreError:
                    continue
                profiles.append({"id": profile["id"], "name": profile["name"]})
        return sorted(
            profiles, key=lambda item: (item["name"].casefold(), item["name"])
        )

    def get_profile(self, character_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._read_profile(character_id))

    def update_profile(
        self,
        character_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            new_name = profile["name"] if name is None else name
            new_description = (
                profile["description"] if description is None else description
            )
            clean_name, clean_description = self._validate_text(
                new_name, new_description
            )
            self._assert_unique_name(clean_name, exclude_id=canonical)
            profile["name"] = clean_name
            profile["description"] = clean_description
            self._atomic_write_json(self._profile_path(canonical), profile)
            return copy.deepcopy(profile)

    def delete_profile(self, character_id: str) -> None:
        canonical = validate_character_id(character_id)
        with self._lock:
            directory = self._character_dir(canonical)
            if not (directory / "profile.json").is_file():
                raise ProfileNotFound(
                    f"Character profile {canonical} no longer exists."
                )
            shutil.rmtree(directory)

    def _stage_upload(
        self,
        directory: Path,
        media_type: str,
        source: BinaryIO,
        original_filename: str,
        content_type: str | None,
    ) -> tuple[Path, str]:
        extension = extension_for_upload(media_type, original_filename, content_type)
        stage_directory = directory / MEDIA_COLLECTIONS[media_type]
        stage_directory.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".upload-", suffix=".tmp", dir=stage_directory
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                shutil.copyfileobj(source, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
            temporary = Path(temporary_name)
            validate_media_file(media_type, temporary, extension)
            return temporary, extension
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _find_media(
        profile: dict[str, Any], media_id: str
    ) -> tuple[str, int, dict[str, str]]:
        canonical = validate_media_id(media_id)
        for media_type, collection in MEDIA_COLLECTIONS.items():
            for index, record in enumerate(profile[collection]):
                if record["id"] == canonical:
                    return media_type, index, record
        raise MediaNotFound(
            f"Media reference {canonical} does not exist for this character."
        )

    def add_media(
        self,
        character_id: str,
        media_type: str,
        source: BinaryIO,
        original_filename: str,
        *,
        label: str = "",
        content_type: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        media_type = self._validate_media_type(media_type)
        clean_label = self._validate_label(label)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            collection = MEDIA_COLLECTIONS[media_type]
            if len(profile[collection]) >= MEDIA_LIMITS[media_type]:
                raise MediaLimitReached(
                    f"A character can store at most {MEDIA_LIMITS[media_type]} "
                    f"{collection} references."
                )
            directory = self._character_dir(canonical)
            temporary, extension = self._stage_upload(
                directory, media_type, source, original_filename, content_type
            )
            media_id = str(uuid.uuid4())
            relative = Path(collection) / f"{media_id}{extension}"
            destination = directory / relative
            try:
                os.replace(temporary, destination)
                profile[collection].append(
                    {"id": media_id, "file": relative.as_posix(), "label": clean_label}
                )
                self._atomic_write_json(self._profile_path(canonical), profile)
            except Exception:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
                raise
            return copy.deepcopy(profile)

    def update_media(
        self,
        character_id: str,
        media_id: str,
        *,
        label: str | object = _UNSET,
        source: BinaryIO | None = None,
        original_filename: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            media_type, _, record = self._find_media(profile, media_id)
            if label is not _UNSET:
                record["label"] = self._validate_label(label)
            directory = self._character_dir(canonical)
            old_path = self._media_file_path(directory, record, media_type)
            new_path = old_path
            backup_path: Path | None = None
            temporary: Path | None = None
            if source is not None:
                if not original_filename:
                    raise InvalidProfile("A filename is required when replacing media.")
                temporary, extension = self._stage_upload(
                    directory, media_type, source, original_filename, content_type
                )
                relative = (
                    Path(MEDIA_COLLECTIONS[media_type]) / f"{record['id']}{extension}"
                )
                new_path = directory / relative
                if new_path.exists():
                    backup_path = new_path.with_name(
                        f".{new_path.name}.{uuid.uuid4().hex}.backup"
                    )
                    os.replace(new_path, backup_path)
                try:
                    os.replace(temporary, new_path)
                    temporary = None
                    record["file"] = relative.as_posix()
                except Exception:
                    if backup_path is not None and backup_path.exists():
                        os.replace(backup_path, new_path)
                    raise
            try:
                self._atomic_write_json(self._profile_path(canonical), profile)
            except Exception:
                if source is not None:
                    try:
                        new_path.unlink()
                    except FileNotFoundError:
                        pass
                    if backup_path is not None and backup_path.exists():
                        os.replace(backup_path, new_path)
                raise
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass
            if backup_path is not None:
                try:
                    backup_path.unlink()
                except FileNotFoundError:
                    pass
            if source is not None and old_path != new_path:
                try:
                    old_path.unlink()
                except FileNotFoundError:
                    pass
            return copy.deepcopy(profile)

    def delete_media(self, character_id: str, media_id: str) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            media_type, index, record = self._find_media(profile, media_id)
            collection = MEDIA_COLLECTIONS[media_type]
            path = self._media_file_path(
                self._character_dir(canonical), record, media_type
            )
            del profile[collection][index]
            for slot in DEFAULT_SLOTS:
                if profile["defaults"][slot] == record["id"]:
                    profile["defaults"][slot] = None
            self._atomic_write_json(self._profile_path(canonical), profile)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return copy.deepcopy(profile)

    def set_defaults(
        self,
        character_id: str,
        *,
        image_1: str | None,
        image_2: str | None,
        audio: str | None,
    ) -> dict[str, Any]:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            values = {"image_1": image_1, "image_2": image_2, "audio": audio}
            located = {
                record["id"]: media_type
                for media_type, collection in MEDIA_COLLECTIONS.items()
                for record in profile[collection]
            }
            clean: dict[str, str | None] = {}
            for slot, value in values.items():
                if value is None:
                    clean[slot] = None
                    continue
                media_id = validate_media_id(value)
                expected_type = "audio" if slot == "audio" else "image"
                actual_type = located.get(media_id)
                if actual_type is None:
                    raise MediaNotFound(
                        f"Media reference {media_id} does not exist for this character."
                    )
                if actual_type != expected_type:
                    raise InvalidProfile(
                        f"Default {slot} must reference {expected_type} media."
                    )
                clean[slot] = media_id
            if clean["image_1"] is not None and clean["image_1"] == clean["image_2"]:
                raise InvalidProfile(
                    "The same image reference cannot be selected as both Image 1 and Image 2."
                )
            profile["defaults"] = clean
            self._atomic_write_json(self._profile_path(canonical), profile)
            return copy.deepcopy(profile)

    @staticmethod
    def _media_file_path(
        directory: Path, record: dict[str, str], media_type: str
    ) -> Path:
        candidate = (directory / record["file"]).resolve()
        expected_parent = (directory / MEDIA_COLLECTIONS[media_type]).resolve()
        if candidate.parent != expected_parent:
            raise ProfileCorrupt("Character profile contains an unsafe media path.")
        return candidate

    def media_path(self, character_id: str, media_id: str) -> Path:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            media_type, _, record = self._find_media(profile, media_id)
            path = self._media_file_path(
                self._character_dir(canonical), record, media_type
            )
            if not path.is_file():
                raise MissingMedia(
                    f'Character "{profile["name"]}" media reference {record["id"]} is missing.'
                )
            return path

    def resolve_selected_media(self, character_id: str) -> dict[str, Path]:
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            defaults = profile["defaults"]
            if not defaults["image_1"] or not defaults["image_2"]:
                raise MissingMedia(
                    f'Character "{profile["name"]}" does not have two image references selected.'
                )
            if not defaults["audio"]:
                raise MissingMedia(
                    f'Character "{profile["name"]}" does not have an audio reference selected.'
                )
            image_records = {record["id"]: record for record in profile["images"]}
            audio_records = {record["id"]: record for record in profile["audio"]}
            selected_records = {
                "image_1": ("image", image_records[defaults["image_1"]]),
                "image_2": ("image", image_records[defaults["image_2"]]),
                "audio": ("audio", audio_records[defaults["audio"]]),
            }
            paths: dict[str, Path] = {}
            directory = self._character_dir(canonical)
            for slot, (media_type, record) in selected_records.items():
                path = self._media_file_path(directory, record, media_type)
                if not path.is_file():
                    raise MissingMedia(
                        f'Character "{profile["name"]}" selected {slot} media file is missing.'
                    )
                paths[slot] = path
            return paths

    def fingerprint(self, character_id: str) -> str:
        """Hash character metadata, default IDs, and only the three selected files."""
        canonical = validate_character_id(character_id)
        with self._lock:
            profile = self._read_profile_unlocked(canonical)
            paths = self.resolve_selected_media(canonical)
            selected_records = {
                slot: next(
                    record
                    for record in (
                        profile["audio"] if slot == "audio" else profile["images"]
                    )
                    if record["id"] == profile["defaults"][slot]
                )
                for slot in DEFAULT_SLOTS
            }
            relevant = {
                "schema_version": profile["schema_version"],
                "id": profile["id"],
                "name": profile["name"],
                "description": profile["description"],
                "defaults": profile["defaults"],
                "selected": {
                    slot: {
                        "id": selected_records[slot]["id"],
                        "file": selected_records[slot]["file"],
                    }
                    for slot in DEFAULT_SLOTS
                },
            }
            digest = hashlib.sha256(
                json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            for slot in DEFAULT_SLOTS:
                digest.update(slot.encode("utf-8"))
                with paths[slot].open("rb") as handle:
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

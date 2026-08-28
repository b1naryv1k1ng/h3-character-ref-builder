"""Filesystem-backed reusable single-image Prop Reference storage."""

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

from .character_store import DATA_DIRECTORY, InvalidMediaId, validate_media_id
from .media import IMAGE_EXTENSIONS, extension_for_upload, validate_media_file

PROP_SCHEMA_VERSION = 1


class PropStoreError(RuntimeError):
    """Base error for expected prop-storage failures."""


class InvalidPropId(PropStoreError):
    pass


class PropNotFound(PropStoreError):
    pass


class PropCorrupt(PropStoreError):
    pass


class PropImageNotFound(PropStoreError):
    pass


class MissingPropImage(PropStoreError):
    pass


class DuplicatePropName(PropStoreError):
    pass


class InvalidProp(PropStoreError):
    pass


def validate_prop_id(prop_id: str) -> str:
    if not isinstance(prop_id, str):
        raise InvalidPropId("Prop Reference UUID must be a string.")
    try:
        canonical = str(uuid.UUID(prop_id))
    except (ValueError, AttributeError) as exc:
        raise InvalidPropId(f"Invalid Prop Reference UUID: {prop_id!r}.") from exc
    if prop_id.lower() != canonical:
        raise InvalidPropId(f"Invalid Prop Reference UUID: {prop_id!r}.")
    return canonical


class PropStore:
    """Manage independent UUID-addressed Prop References beneath one trusted root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.props_root = self.root / "props"
        self.props_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _prop_dir(self, prop_id: str) -> Path:
        canonical = validate_prop_id(prop_id)
        candidate = (self.props_root / canonical).resolve()
        if candidate.parent != self.props_root.resolve():
            raise InvalidPropId("Prop id escapes the managed prop directory.")
        return candidate

    def _prop_path(self, prop_id: str) -> Path:
        return self._prop_dir(prop_id) / "prop.json"

    @staticmethod
    def _validate_text(name: Any, description: Any) -> tuple[str, str]:
        if not isinstance(name, str):
            raise InvalidProp("Prop name must be a string.")
        clean_name = name.strip()
        if not clean_name:
            raise InvalidProp("Prop name is required.")
        if len(clean_name) > 200:
            raise InvalidProp("Prop name must be 200 characters or fewer.")
        if not isinstance(description, str):
            raise InvalidProp("Prop description must be a string.")
        clean_description = description.strip()
        if len(clean_description) > 20_000:
            raise InvalidProp("Prop description must be 20,000 characters or fewer.")
        return clean_name, clean_description

    @staticmethod
    def _validate_reference_image(
        record: Any, expected_id: str
    ) -> dict[str, str] | None:
        if record is None:
            return None
        if not isinstance(record, dict) or set(record) != {"id", "file"}:
            raise PropCorrupt(
                f"Prop Reference {expected_id} contains an invalid reference image."
            )
        try:
            image_id = validate_media_id(record["id"])
        except InvalidMediaId as exc:
            raise PropCorrupt(
                f"Prop Reference {expected_id} contains an invalid image id."
            ) from exc
        file_value = record["file"]
        if not isinstance(file_value, str):
            raise PropCorrupt(
                f"Prop Reference {expected_id} contains an invalid image filename."
            )
        path = Path(file_value)
        if (
            path.is_absolute()
            or len(path.parts) != 2
            or path.parts[0] != "images"
            or Path(path.parts[1]).stem != image_id
            or Path(path.parts[1]).suffix.lower() not in IMAGE_EXTENSIONS
        ):
            raise PropCorrupt(
                f"Prop Reference {expected_id} contains an unsafe image filename."
            )
        return {"id": image_id, "file": path.as_posix()}

    @classmethod
    def _validate_prop_data(cls, data: Any, expected_id: str) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "id",
            "name",
            "description",
            "reference_image",
        }:
            raise PropCorrupt(f"Prop Reference {expected_id} has invalid fields.")
        if data["schema_version"] != PROP_SCHEMA_VERSION or data["id"] != expected_id:
            raise PropCorrupt(
                f"Prop Reference {expected_id} has invalid identity data."
            )
        try:
            name, description = cls._validate_text(data["name"], data["description"])
        except InvalidProp as exc:
            raise PropCorrupt(
                f"Prop Reference {expected_id} is invalid: {exc}"
            ) from exc
        return {
            "schema_version": PROP_SCHEMA_VERSION,
            "id": expected_id,
            "name": name,
            "description": description,
            "reference_image": cls._validate_reference_image(
                data["reference_image"], expected_id
            ),
        }

    @staticmethod
    def _atomic_write(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".prop-", suffix=".tmp", dir=path.parent
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

    def _read_unlocked(self, prop_id: str) -> dict[str, Any]:
        canonical = validate_prop_id(prop_id)
        path = self._prop_path(canonical)
        if not path.is_file():
            raise PropNotFound(f"Prop Reference {canonical} no longer exists.")
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise PropCorrupt(f"Prop Reference {canonical} is malformed.") from exc
        return self._validate_prop_data(data, canonical)

    def _assert_unique_name(self, name: str, exclude_id: str | None = None) -> None:
        folded = name.casefold()
        for prop in self.list_props():
            if prop["id"] != exclude_id and prop["name"].casefold() == folded:
                raise DuplicatePropName(
                    f'A Prop Reference named "{name}" already exists '
                    "(names are case-insensitive)."
                )

    def create_prop(self, name: str, description: str = "") -> dict[str, Any]:
        clean_name, clean_description = self._validate_text(name, description)
        with self._lock:
            self._assert_unique_name(clean_name)
            prop_id = str(uuid.uuid4())
            directory = self._prop_dir(prop_id)
            directory.mkdir(parents=False, exist_ok=False)
            prop = {
                "schema_version": PROP_SCHEMA_VERSION,
                "id": prop_id,
                "name": clean_name,
                "description": clean_description,
                "reference_image": None,
            }
            try:
                self._atomic_write(directory / "prop.json", prop)
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return copy.deepcopy(prop)

    def list_props(self) -> list[dict[str, Any]]:
        props: list[dict[str, Any]] = []
        with self._lock:
            for directory in self.props_root.iterdir():
                if not directory.is_dir():
                    continue
                try:
                    prop = self._read_unlocked(directory.name)
                except PropStoreError:
                    continue
                usable = False
                if prop["reference_image"] is not None:
                    try:
                        usable = self._reference_image_file_path(
                            self._prop_dir(prop["id"]), prop["reference_image"]
                        ).is_file()
                    except PropStoreError:
                        usable = False
                props.append({"id": prop["id"], "name": prop["name"], "usable": usable})
        return sorted(props, key=lambda item: (item["name"].casefold(), item["name"]))

    def list_usable_props(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"id": item["id"], "name": item["name"]}
                for item in self.list_props()
                if item["usable"]
            ]

    def get_prop(self, prop_id: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._read_unlocked(prop_id))

    def update_prop(
        self,
        prop_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_prop_id(prop_id)
        with self._lock:
            prop = self._read_unlocked(canonical)
            clean_name, clean_description = self._validate_text(
                prop["name"] if name is None else name,
                prop["description"] if description is None else description,
            )
            self._assert_unique_name(clean_name, exclude_id=canonical)
            prop["name"] = clean_name
            prop["description"] = clean_description
            self._atomic_write(self._prop_path(canonical), prop)
            return copy.deepcopy(prop)

    @staticmethod
    def _reference_image_file_path(directory: Path, record: dict[str, str]) -> Path:
        candidate = (directory / record["file"]).resolve()
        expected_parent = (directory / "images").resolve()
        if candidate.parent != expected_parent:
            raise PropCorrupt("Prop Reference contains an unsafe image path.")
        return candidate

    def _stage_reference_image(
        self,
        directory: Path,
        source: BinaryIO,
        original_filename: str,
        content_type: str | None,
    ) -> tuple[Path, str]:
        extension = extension_for_upload("image", original_filename, content_type)
        images_directory = directory / "images"
        images_directory.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".upload-", suffix=".tmp", dir=images_directory
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                shutil.copyfileobj(source, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
            temporary = Path(temporary_name)
            validate_media_file("image", temporary, extension)
            return temporary, extension
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def set_reference_image(
        self,
        prop_id: str,
        source: BinaryIO,
        original_filename: str,
        *,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        canonical = validate_prop_id(prop_id)
        with self._lock:
            prop = self._read_unlocked(canonical)
            directory = self._prop_dir(canonical)
            temporary, extension = self._stage_reference_image(
                directory, source, original_filename, content_type
            )
            old_record = prop["reference_image"]
            image_id = old_record["id"] if old_record is not None else str(uuid.uuid4())
            relative = Path("images") / f"{image_id}{extension}"
            destination = directory / relative
            old_path = (
                self._reference_image_file_path(directory, old_record)
                if old_record is not None
                else None
            )
            backup_path: Path | None = None
            if destination.exists():
                backup_path = destination.with_name(
                    f".{destination.name}.{uuid.uuid4().hex}.backup"
                )
                os.replace(destination, backup_path)
            try:
                os.replace(temporary, destination)
                prop["reference_image"] = {
                    "id": image_id,
                    "file": relative.as_posix(),
                }
                self._atomic_write(self._prop_path(canonical), prop)
            except Exception:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
                if backup_path is not None and backup_path.exists():
                    os.replace(backup_path, destination)
                raise
            if backup_path is not None:
                try:
                    backup_path.unlink()
                except FileNotFoundError:
                    pass
            if old_path is not None and old_path != destination:
                try:
                    old_path.unlink()
                except FileNotFoundError:
                    pass
            return copy.deepcopy(prop)

    def reference_image_path(self, prop_id: str) -> Path:
        canonical = validate_prop_id(prop_id)
        with self._lock:
            prop = self._read_unlocked(canonical)
            record = prop["reference_image"]
            if record is None:
                raise PropImageNotFound(
                    f"Prop Reference {canonical} has no reference image."
                )
            path = self._reference_image_file_path(self._prop_dir(canonical), record)
            if not path.is_file():
                raise MissingPropImage(
                    f'Prop Reference "{prop["name"]}" image is missing.'
                )
            return path

    def delete_prop(self, prop_id: str) -> None:
        canonical = validate_prop_id(prop_id)
        with self._lock:
            directory = self._prop_dir(canonical)
            if not (directory / "prop.json").is_file():
                raise PropNotFound(f"Prop Reference {canonical} no longer exists.")
            shutil.rmtree(directory)

    def fingerprint(self, prop_id: str) -> str:
        """Hash all selected-prop prompt and output state."""
        canonical = validate_prop_id(prop_id)
        with self._lock:
            prop = self._read_unlocked(canonical)
            relevant = {
                "schema_version": prop["schema_version"],
                "id": prop["id"],
                "name": prop["name"],
                "description": prop["description"],
                "reference_image": prop["reference_image"],
            }
            digest = hashlib.sha256(
                json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            if prop["reference_image"] is not None:
                with self.reference_image_path(canonical).open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            return digest.hexdigest()


_DEFAULT_STORES: dict[Path, PropStore] = {}
_DEFAULT_STORES_LOCK = threading.Lock()


def get_default_prop_store() -> PropStore:
    import folder_paths

    root = (Path(folder_paths.get_user_directory()) / DATA_DIRECTORY).resolve()
    with _DEFAULT_STORES_LOCK:
        store = _DEFAULT_STORES.get(root)
        if store is None:
            store = PropStore(root)
            _DEFAULT_STORES[root] = store
        return store

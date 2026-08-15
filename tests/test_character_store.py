from __future__ import annotations

import io
import json
import uuid
import wave

import pytest
from PIL import Image

from h3_character_ref_builder.character_store import (
    CharacterStore,
    DuplicateCharacterName,
    InvalidCharacterId,
    InvalidProfile,
    ProfileCorrupt,
    ProfileNotFound,
)


def image_bytes(fmt: str, color=(20, 80, 140)) -> io.BytesIO:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format=fmt)
    output.seek(0)
    return output


def wav_bytes(sample: int = 0) -> io.BytesIO:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(int(sample).to_bytes(2, "little", signed=True) * 80)
    output.seek(0)
    return output


@pytest.fixture
def store(tmp_path):
    return CharacterStore(tmp_path / "managed")


def complete_profile(store: CharacterStore, name="Ari"):
    profile = store.create_profile(name)
    character_id = profile["id"]
    store.replace_media(character_id, "reference_image_1", image_bytes("PNG"), "one.png")
    store.replace_media(character_id, "reference_image_2", image_bytes("WEBP"), "two.webp")
    store.replace_media(character_id, "reference_audio", wav_bytes(), "voice.wav")
    return store.get_profile(character_id)


def test_create_generates_uuid_and_lists_case_insensitively(store):
    zed = store.create_profile("zed")
    alpha = store.create_profile("Alpha")

    assert str(uuid.UUID(zed["id"])) == zed["id"]
    assert zed == {
        "schema_version": 1,
        "id": zed["id"],
        "name": "zed",
        "description": "",
        "reference_image_1": None,
        "reference_image_2": None,
        "reference_audio": None,
    }
    assert store.list_profiles() == [
        {"id": alpha["id"], "name": "Alpha"},
        {"id": zed["id"], "name": "zed"},
    ]


def test_duplicate_visible_names_are_rejected_case_insensitively(store):
    store.create_profile("Ari")
    with pytest.raises(DuplicateCharacterName, match="already exists"):
        store.create_profile("  ARI  ")


def test_rename_and_description_update_keep_uuid(store):
    original = store.create_profile("Ari", "first")
    updated = store.update_profile(original["id"], name="Aria", description="second")

    assert updated["id"] == original["id"]
    assert updated["name"] == "Aria"
    assert updated["description"] == "second"


def test_delete_removes_profile(store):
    profile = store.create_profile("Ari")
    store.delete_profile(profile["id"])

    assert store.list_profiles() == []
    with pytest.raises(ProfileNotFound, match="no longer exists"):
        store.get_profile(profile["id"])


def test_media_slot_validation_and_path_traversal_rejection(store):
    profile = store.create_profile("Ari")
    with pytest.raises(InvalidProfile, match="Invalid media slot"):
        store.replace_media(profile["id"], "../../escape", image_bytes("PNG"), "x.png")
    with pytest.raises(InvalidCharacterId):
        store.get_profile("../../escape")
    with pytest.raises(InvalidCharacterId):
        store.get_profile(f"{profile['id']}/../escape")


def test_media_replacement_updates_profile_and_removes_old_extension(store):
    profile = store.create_profile("Ari")
    character_id = profile["id"]
    first = store.replace_media(
        character_id, "reference_image_1", image_bytes("PNG"), "client-name.png"
    )
    old_path = store.media_path(character_id, "reference_image_1")
    assert first["reference_image_1"] == "reference_image_1.png"

    second = store.replace_media(
        character_id,
        "reference_image_1",
        image_bytes("JPEG", (200, 10, 10)),
        "../../untrusted-name.jpg",
    )

    assert second["reference_image_1"] == "reference_image_1.jpg"
    assert store.media_path(character_id, "reference_image_1").name == "reference_image_1.jpg"
    assert not old_path.exists()
    assert not list(old_path.parent.glob("reference_image_1.*.upload"))


def test_malformed_and_missing_profiles_are_handled(store):
    missing_id = str(uuid.uuid4())
    with pytest.raises(ProfileNotFound):
        store.get_profile(missing_id)

    corrupt_id = str(uuid.uuid4())
    directory = store.characters_root / corrupt_id
    directory.mkdir()
    (directory / "profile.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ProfileCorrupt, match="malformed"):
        store.get_profile(corrupt_id)
    assert all(item["id"] != corrupt_id for item in store.list_profiles())


def test_profile_rejects_unsafe_managed_filename(store):
    profile = store.create_profile("Ari")
    profile_path = store.characters_root / profile["id"] / "profile.json"
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    data["reference_image_1"] = "../secret.png"
    profile_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProfileCorrupt, match="unsafe"):
        store.get_profile(profile["id"])


def test_fingerprint_changes_for_metadata_and_selected_media(store):
    profile = complete_profile(store)
    character_id = profile["id"]
    initial = store.fingerprint(character_id)

    store.update_profile(character_id, description="changed")
    metadata_changed = store.fingerprint(character_id)
    assert metadata_changed != initial

    store.replace_media(
        character_id, "reference_audio", wav_bytes(sample=1000), "replacement.wav"
    )
    assert store.fingerprint(character_id) != metadata_changed


def test_unrelated_character_does_not_change_selected_fingerprint(store):
    selected = complete_profile(store, "Ari")
    before = store.fingerprint(selected["id"])
    other = complete_profile(store, "Rachel")
    store.update_profile(other["id"], description="unrelated edit")

    assert store.fingerprint(selected["id"]) == before

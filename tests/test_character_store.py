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
    InvalidMediaId,
    InvalidProfile,
    MediaLimitReached,
    MediaNotFound,
    MissingMedia,
    ProfileCorrupt,
    ProfileNotFound,
)


def image_bytes(fmt: str = "PNG", color=(20, 80, 140)) -> io.BytesIO:
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


def add_image(store, character_id, label, color=(20, 80, 140), extension="png"):
    fmt = "JPEG" if extension in {"jpg", "jpeg"} else extension.upper()
    profile = store.add_media(
        character_id,
        "image",
        image_bytes(fmt, color),
        f"client.{extension}",
        label=label,
    )
    return profile["images"][-1]


def add_audio(store, character_id, label, sample=0):
    profile = store.add_media(
        character_id,
        "audio",
        wav_bytes(sample),
        "client.wav",
        label=label,
    )
    return profile["audio"][-1]


def complete_profile(store: CharacterStore, name="Ari", extra=False):
    profile = store.create_profile(name)
    character_id = profile["id"]
    image_1 = add_image(store, character_id, "Front", (20, 80, 140))
    image_2 = add_image(store, character_id, "Three quarter", (80, 20, 140))
    image_3 = add_image(store, character_id, "Unused", (140, 80, 20)) if extra else None
    audio_1 = add_audio(store, character_id, "Neutral", 0)
    audio_2 = add_audio(store, character_id, "Unused audio", 200) if extra else None
    store.set_defaults(
        character_id,
        image_1=image_1["id"],
        image_2=image_2["id"],
        audio=audio_1["id"],
    )
    return store.get_profile(character_id), image_3, audio_2


def test_create_generates_v3_uuid_and_lists_case_insensitively(store):
    zed = store.create_profile("zed")
    alpha = store.create_profile("Alpha")

    assert str(uuid.UUID(zed["id"])) == zed["id"]
    assert zed == {
        "schema_version": 3,
        "id": zed["id"],
        "name": "zed",
        "description": "",
        "images": [],
        "audio": [],
        "defaults": {"image_1": None, "image_2": None, "audio": None},
    }
    assert store.list_profiles() == [
        {"id": alpha["id"], "name": "Alpha"},
        {"id": zed["id"], "name": "zed"},
    ]


def test_duplicate_names_rename_description_and_delete(store):
    original = store.create_profile("Ari", "first")
    with pytest.raises(DuplicateCharacterName):
        store.create_profile(" ARI ")

    updated = store.update_profile(original["id"], name="Aria", description="second")
    assert updated["id"] == original["id"]
    assert (updated["name"], updated["description"]) == ("Aria", "second")

    store.delete_profile(original["id"])
    with pytest.raises(ProfileNotFound, match="no longer exists"):
        store.get_profile(original["id"])


def test_v1_migration_preserves_defaults_and_is_idempotent(store):
    character_id = str(uuid.uuid4())
    directory = store.characters_root / character_id
    directory.mkdir()
    legacy = {
        "schema_version": 1,
        "id": character_id,
        "name": "Legacy Ari",
        "description": "existing",
        "reference_image_1": "reference_image_1.png",
        "reference_image_2": "reference_image_2.jpg",
        "reference_audio": "reference_audio.wav",
    }
    (directory / "profile.json").write_text(json.dumps(legacy), encoding="utf-8")
    (directory / legacy["reference_image_1"]).write_bytes(image_bytes().getvalue())
    (directory / legacy["reference_image_2"]).write_bytes(
        image_bytes("JPEG", (120, 30, 10)).getvalue()
    )
    (directory / legacy["reference_audio"]).write_bytes(wav_bytes().getvalue())

    migrated = store.get_profile(character_id)
    first_json = (directory / "profile.json").read_bytes()
    selected = store.resolve_selected_media(character_id)

    assert migrated["schema_version"] == 3
    assert len(migrated["images"]) == 2
    assert len(migrated["audio"]) == 1
    assert migrated["defaults"]["image_1"] == migrated["images"][0]["id"]
    assert migrated["defaults"]["image_2"] == migrated["images"][1]["id"]
    assert migrated["defaults"]["audio"] == migrated["audio"][0]["id"]
    assert selected["image_1"].read_bytes() == image_bytes().getvalue()
    assert all(
        not (directory / filename).exists()
        for filename in legacy.values()
        if isinstance(filename, str) and filename.startswith("reference_")
    )

    migrated_again = store.get_profile(character_id)
    assert migrated_again == migrated
    assert (directory / "profile.json").read_bytes() == first_json


def test_add_multiple_references_with_stable_media_uuids(store):
    profile = store.create_profile("Ari")
    image_1 = add_image(store, profile["id"], "Front")
    image_2 = add_image(store, profile["id"], "Full body")
    audio_1 = add_audio(store, profile["id"], "Neutral")
    audio_2 = add_audio(store, profile["id"], "Excited", 100)

    result = store.get_profile(profile["id"])
    assert [record["id"] for record in result["images"]] == [
        image_1["id"],
        image_2["id"],
    ]
    assert [record["id"] for record in result["audio"]] == [
        audio_1["id"],
        audio_2["id"],
    ]
    for media_id in [image_1["id"], image_2["id"], audio_1["id"], audio_2["id"]]:
        assert str(uuid.UUID(media_id)) == media_id


def test_media_limits_are_enforced(store):
    profile = store.create_profile("Ari")
    for index in range(9):
        add_image(store, profile["id"], f"Image {index}", (index, 10, 20))
    with pytest.raises(MediaLimitReached, match="at most 9"):
        add_image(store, profile["id"], "Too many")

    for index in range(3):
        add_audio(store, profile["id"], f"Audio {index}", index)
    with pytest.raises(MediaLimitReached, match="at most 3"):
        add_audio(store, profile["id"], "Too many")


def test_replace_preserves_uuid_relabels_and_cleans_old_extension(store):
    profile = store.create_profile("Ari")
    image = add_image(store, profile["id"], "Front")
    old_path = store.media_path(profile["id"], image["id"])

    replaced = store.update_media(
        profile["id"],
        image["id"],
        label="Updated front",
        source=image_bytes("JPEG", (200, 10, 10)),
        original_filename="../../ignored.jpg",
    )
    record = replaced["images"][0]

    assert record["id"] == image["id"]
    assert record["label"] == "Updated front"
    assert record["file"].endswith(f"{image['id']}.jpg")
    assert not old_path.exists()
    assert store.media_path(profile["id"], image["id"]).is_file()


def test_delete_media_removes_file_and_clears_selected_default(store):
    profile, _, _ = complete_profile(store)
    selected_id = profile["defaults"]["image_1"]
    path = store.media_path(profile["id"], selected_id)

    updated = store.delete_media(profile["id"], selected_id)

    assert updated["defaults"]["image_1"] is None
    assert updated["defaults"]["image_2"] is not None
    assert not path.exists()
    with pytest.raises(MediaNotFound):
        store.media_path(profile["id"], selected_id)


def test_default_selection_validation(store):
    profile = store.create_profile("Ari")
    image_1 = add_image(store, profile["id"], "Front")
    image_2 = add_image(store, profile["id"], "Side")
    audio = add_audio(store, profile["id"], "Voice")

    selected = store.set_defaults(
        profile["id"], image_1=image_1["id"], image_2=image_2["id"], audio=audio["id"]
    )
    assert selected["defaults"] == {
        "image_1": image_1["id"],
        "image_2": image_2["id"],
        "audio": audio["id"],
    }

    with pytest.raises(InvalidProfile, match="same image"):
        store.set_defaults(
            profile["id"],
            image_1=image_1["id"],
            image_2=image_1["id"],
            audio=audio["id"],
        )
    with pytest.raises(InvalidProfile, match="must reference image"):
        store.set_defaults(
            profile["id"], image_1=audio["id"], image_2=image_2["id"], audio=audio["id"]
        )
    with pytest.raises(InvalidProfile, match="must reference audio"):
        store.set_defaults(
            profile["id"],
            image_1=image_1["id"],
            image_2=image_2["id"],
            audio=image_1["id"],
        )


def test_incomplete_profile_has_useful_errors(store):
    profile = store.create_profile("Ari")
    with pytest.raises(MissingMedia, match="two image references selected"):
        store.resolve_selected_media(profile["id"])
    image_1 = add_image(store, profile["id"], "One")
    image_2 = add_image(store, profile["id"], "Two")
    store.set_defaults(
        profile["id"], image_1=image_1["id"], image_2=image_2["id"], audio=None
    )
    with pytest.raises(MissingMedia, match="audio reference selected"):
        store.resolve_selected_media(profile["id"])


def test_fingerprint_tracks_selected_outputs_not_unused_references(store):
    profile, unused_image, unused_audio = complete_profile(store, extra=True)
    character_id = profile["id"]
    initial = store.fingerprint(character_id)

    store.update_media(character_id, unused_image["id"], label="Relabeled unused")
    assert store.fingerprint(character_id) == initial
    store.update_media(
        character_id,
        unused_audio["id"],
        source=wav_bytes(500),
        original_filename="unused-replacement.wav",
    )
    assert store.fingerprint(character_id) == initial

    selected_image = profile["defaults"]["image_1"]
    store.update_media(
        character_id,
        selected_image,
        source=image_bytes("PNG", (250, 1, 2)),
        original_filename="selected.png",
    )
    selected_changed = store.fingerprint(character_id)
    assert selected_changed != initial

    store.set_defaults(
        character_id,
        image_1=unused_image["id"],
        image_2=profile["defaults"]["image_2"],
        audio=profile["defaults"]["audio"],
    )
    assert store.fingerprint(character_id) != selected_changed


def test_metadata_changes_but_other_character_does_not_invalidate(store):
    selected, _, _ = complete_profile(store, "Ari")
    before = store.fingerprint(selected["id"])
    other, _, _ = complete_profile(store, "Rachel")
    store.update_media(
        other["id"],
        other["defaults"]["image_1"],
        source=image_bytes("PNG", (3, 4, 5)),
        original_filename="other-selected.png",
    )
    assert store.fingerprint(selected["id"]) == before

    store.update_profile(selected["id"], description="changed")
    assert store.fingerprint(selected["id"]) != before


def test_malformed_profile_and_path_traversal_protections(store):
    profile = store.create_profile("Ari")
    with pytest.raises(InvalidCharacterId):
        store.get_profile("../../escape")
    with pytest.raises(InvalidMediaId):
        store.media_path(profile["id"], "../../escape")

    image = add_image(store, profile["id"], "Front")
    profile_path = store.characters_root / profile["id"] / "profile.json"
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    data["images"][0]["file"] = "../secret.png"
    profile_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProfileCorrupt, match="unsafe"):
        store.get_profile(profile["id"])
    assert image["id"]


def test_missing_and_malformed_profile_handling(store):
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

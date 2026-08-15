from __future__ import annotations

import json

import pytest

from h3_character_ref_builder.character_store import InvalidProfile

from .test_character_store import add_audio, add_image, complete_profile, image_bytes


def test_v2_migration_assigns_roles_without_changing_uuid_or_paths(store):
    profile, unused_image, unused_audio = complete_profile(store, "V2 Ari", extra=True)
    profile_path = store.characters_root / profile["id"] / "profile.json"
    v2 = json.loads(profile_path.read_text(encoding="utf-8"))
    v2["schema_version"] = 2
    for record in [*v2["images"], *v2["audio"]]:
        record.pop("role")
    profile_path.write_text(json.dumps(v2), encoding="utf-8")
    original_ids = [record["id"] for record in [*v2["images"], *v2["audio"]]]
    original_paths = [record["file"] for record in [*v2["images"], *v2["audio"]]]

    migrated = store.get_profile(profile["id"])
    first_json = profile_path.read_bytes()

    assert migrated["schema_version"] == 3
    records = {
        record["id"]: record for record in [*migrated["images"], *migrated["audio"]]
    }
    assert records[migrated["defaults"]["image_1"]]["role"] == "face_identity"
    assert records[migrated["defaults"]["image_2"]]["role"] == "full_body_identity"
    assert records[migrated["defaults"]["audio"]]["role"] == "voice_identity"
    assert records[unused_image["id"]]["role"] == "general"
    assert records[unused_audio["id"]]["role"] == "general"
    assert [
        record["id"] for record in [*migrated["images"], *migrated["audio"]]
    ] == original_ids
    assert [
        record["file"] for record in [*migrated["images"], *migrated["audio"]]
    ] == original_paths
    assert store.get_profile(profile["id"]) == migrated
    assert profile_path.read_bytes() == first_json


@pytest.mark.parametrize(
    "role",
    [
        "face_identity",
        "full_body_identity",
        "alternate_identity",
        "wardrobe",
        "pose_orientation",
        "expression",
        "general",
    ],
)
def test_valid_image_roles_are_persisted_without_file_replacement(store, role):
    profile = store.create_profile("Ari")
    image = add_image(store, profile["id"], "Front")
    path = store.media_path(profile["id"], image["id"])
    before = path.read_bytes()

    updated = store.update_media(profile["id"], image["id"], role=role)

    assert updated["images"][0]["id"] == image["id"]
    assert updated["images"][0]["role"] == role
    assert path.read_bytes() == before


@pytest.mark.parametrize("role", ["voice_identity", "delivery_emotion", "general"])
def test_valid_audio_roles_are_persisted(store, role):
    profile = store.create_profile("Ari")
    audio = add_audio(store, profile["id"], "Voice")
    updated = store.update_media(profile["id"], audio["id"], role=role)
    assert updated["audio"][0]["id"] == audio["id"]
    assert updated["audio"][0]["role"] == role


def test_invalid_roles_are_rejected_for_media_type(store):
    profile = store.create_profile("Ari")
    image = add_image(store, profile["id"], "Front")
    audio = add_audio(store, profile["id"], "Voice")
    with pytest.raises(InvalidProfile, match="Invalid image role"):
        store.update_media(profile["id"], image["id"], role="voice_identity")
    with pytest.raises(InvalidProfile, match="Invalid audio role"):
        store.update_media(profile["id"], audio["id"], role="face_identity")


def test_identity_prefix_is_normalized_on_storage(store):
    profile = store.create_profile(
        "Ari", "  <Subject 1> is a scar above the left eyebrow. "
    )
    assert profile["description"] == "a scar above the left eyebrow."


def test_character_fingerprint_tracks_selected_roles_and_identity_only(store):
    profile, unused_image, _ = complete_profile(store, "Ari", extra=True)
    character_id = profile["id"]
    initial = store.fingerprint(character_id)

    store.update_media(character_id, unused_image["id"], role="wardrobe")
    assert store.fingerprint(character_id) == initial

    store.update_media(character_id, profile["defaults"]["image_1"], role="expression")
    role_changed = store.fingerprint(character_id)
    assert role_changed != initial

    store.update_profile(character_id, name="Renamed Ari")
    assert store.fingerprint(character_id) == role_changed
    store.update_profile(character_id, description="stable identity details")
    assert store.fingerprint(character_id) != role_changed


def test_selected_content_still_changes_v3_fingerprint(store):
    profile, _, _ = complete_profile(store)
    initial = store.fingerprint(profile["id"])
    store.update_media(
        profile["id"],
        profile["defaults"]["image_1"],
        source=image_bytes("PNG", (201, 2, 3)),
        original_filename="selected.png",
    )
    assert store.fingerprint(profile["id"]) != initial

from __future__ import annotations

import json
import uuid

import pytest

from h3_character_ref_builder.scene_store import (
    DuplicateSceneName,
    InvalidSceneId,
    SceneCorrupt,
    SceneNotFound,
    SceneStore,
)


@pytest.fixture
def scenes(tmp_path):
    return SceneStore(tmp_path / "managed")


def test_scene_crud_sorting_uuid_stability_and_prefix_normalization(scenes):
    zed = scenes.create_scene("zed", "<Subject 2> is a dark studio")
    alpha = scenes.create_scene("Alpha", "  a bright room  ")

    assert str(uuid.UUID(zed["id"])) == zed["id"]
    assert zed["definition"] == "a dark studio"
    assert scenes.list_scenes() == [
        {"id": alpha["id"], "name": "Alpha"},
        {"id": zed["id"], "name": "zed"},
    ]

    updated = scenes.update_scene(
        zed["id"], name="Beach", definition="<Subject 2> is warm sand\nand surf"
    )
    assert updated["id"] == zed["id"]
    assert updated["definition"] == "warm sand\nand surf"

    scenes.delete_scene(zed["id"])
    with pytest.raises(SceneNotFound, match="no longer exists"):
        scenes.get_scene(zed["id"])


def test_duplicate_scene_names_are_case_insensitive(scenes):
    scenes.create_scene("Tropical Beach")
    with pytest.raises(DuplicateSceneName):
        scenes.create_scene(" tropical BEACH ")


def test_scene_malformed_uuid_and_path_validation(scenes):
    with pytest.raises(InvalidSceneId):
        scenes.get_scene("../../escape")
    corrupt_id = str(uuid.uuid4())
    directory = scenes.scenes_root / corrupt_id
    directory.mkdir()
    (directory / "scene.json").write_text("{bad json", encoding="utf-8")
    with pytest.raises(SceneCorrupt, match="malformed"):
        scenes.get_scene(corrupt_id)
    assert all(item["id"] != corrupt_id for item in scenes.list_scenes())


def test_scene_schema_rejects_mismatched_identity(scenes):
    scene = scenes.create_scene("Room", "plain walls")
    path = scenes.scenes_root / scene["id"] / "scene.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["id"] = str(uuid.uuid4())
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SceneCorrupt, match="identity"):
        scenes.get_scene(scene["id"])

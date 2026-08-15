import pytest

from h3_character_ref_builder.character_store import CharacterStore


@pytest.fixture
def store(tmp_path):
    return CharacterStore(tmp_path / "managed")

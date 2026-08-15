from __future__ import annotations

import wave

import pytest
from PIL import Image

from h3_character_ref_builder.media import InvalidMedia, load_audio, load_image


def test_load_image_returns_native_image_tensor(tmp_path):
    pytest.importorskip("torch")
    path = tmp_path / "oriented.png"
    Image.new("RGB", (5, 3), (255, 128, 0)).save(path)

    tensor = load_image(path)

    assert tuple(tensor.shape) == (1, 3, 5, 3)
    assert tensor.dtype.is_floating_point
    assert float(tensor.min()) >= 0.0
    assert float(tensor.max()) <= 1.0


def test_load_audio_returns_native_audio_dict(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("av")
    path = tmp_path / "voice.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes((100).to_bytes(2, "little", signed=True) * 100)

    audio = load_audio(path)

    assert set(audio) == {"waveform", "sample_rate"}
    assert audio["sample_rate"] == 8_000
    assert tuple(audio["waveform"].shape) == (1, 1, 100)
    assert audio["waveform"].dtype.is_floating_point


def test_invalid_image_content_is_rejected(tmp_path):
    from h3_character_ref_builder.media import validate_media_file

    path = tmp_path / "fake.upload"
    path.write_bytes(b"not an image")
    with pytest.raises(InvalidMedia, match="valid image"):
        validate_media_file("reference_image_1", path, ".png")

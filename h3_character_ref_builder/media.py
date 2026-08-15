"""Validation and native ComfyUI media loading helpers."""

from __future__ import annotations

import wave
from pathlib import Path

MEDIA_SLOTS = (
    "reference_image_1",
    "reference_image_2",
    "reference_audio",
)
MEDIA_TYPES = ("image", "audio")
IMAGE_SLOTS = frozenset({"reference_image_1", "reference_image_2"})
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"})


class InvalidMedia(ValueError):
    pass


def normalize_media_type(media_type_or_slot: str) -> str:
    if media_type_or_slot == "image" or media_type_or_slot in IMAGE_SLOTS:
        return "image"
    if media_type_or_slot in {"audio", "reference_audio"}:
        return "audio"
    raise InvalidMedia(f"Invalid media type or slot: {media_type_or_slot!r}.")


def extension_for_upload(
    media_type_or_slot: str, original_filename: str, content_type: str | None = None
) -> str:
    del content_type  # File content is inspected after upload; MIME is not trusted.
    media_type = normalize_media_type(media_type_or_slot)
    if not isinstance(original_filename, str) or not original_filename:
        raise InvalidMedia("An uploaded media filename with an extension is required.")
    extension = Path(original_filename).suffix.lower()
    allowed = IMAGE_EXTENSIONS if media_type == "image" else AUDIO_EXTENSIONS
    if extension not in allowed:
        raise InvalidMedia(
            f"Unsupported file extension {extension or '(none)'} for {media_type}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
    return extension


def validate_media_file(media_type_or_slot: str, path: Path, extension: str) -> None:
    media_type = normalize_media_type(media_type_or_slot)
    if path.stat().st_size == 0:
        raise InvalidMedia("Uploaded media file is empty.")
    if media_type == "image":
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(path) as image:
                image.verify()
                detected = (image.format or "").upper()
        except (OSError, UnidentifiedImageError) as exc:
            raise InvalidMedia("Uploaded file is not a valid image.") from exc
        expected_format = {
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".webp": "WEBP",
        }[extension]
        if detected != expected_format:
            raise InvalidMedia(
                "Uploaded image content does not match its file extension."
            )
        return

    try:
        import av

        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise InvalidMedia("Uploaded file contains no audio stream.")
    except ImportError:
        if extension != ".wav":
            raise InvalidMedia(
                "This ComfyUI installation cannot validate non-WAV audio because PyAV is unavailable."
            )
        try:
            with wave.open(str(path), "rb") as wav_file:
                if wav_file.getnchannels() < 1 or wav_file.getframerate() < 1:
                    raise InvalidMedia("Uploaded WAV has invalid audio metadata.")
        except (OSError, wave.Error, EOFError) as exc:
            raise InvalidMedia("Uploaded file is not a valid WAV audio file.") from exc
    except InvalidMedia:
        raise
    except Exception as exc:
        raise InvalidMedia("Uploaded file is not valid decodable audio.") from exc


def load_image(path: str | Path):
    """Load the first image frame using ComfyUI's IMAGE tensor convention."""
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        array = np.array(image, dtype=np.float32) / 255.0
        tensor = torch.from_numpy(array).unsqueeze(0)

    try:
        import comfy.model_management as model_management

        tensor = tensor.to(
            device=model_management.intermediate_device(),
            dtype=model_management.intermediate_dtype(),
        )
    except (ImportError, AttributeError):
        pass
    return tensor


def _float32_pcm(waveform):
    import torch

    if waveform.dtype.is_floating_point:
        return waveform.float()
    if waveform.dtype == torch.uint8:
        return (waveform.float() - 128.0) / 128.0
    if waveform.dtype == torch.int16:
        return waveform.float() / (2**15)
    if waveform.dtype == torch.int32:
        return waveform.float() / (2**31)
    raise InvalidMedia(f"Unsupported decoded audio dtype: {waveform.dtype}.")


def load_audio(path: str | Path) -> dict:
    """Decode audio with ComfyUI's PyAV stack and return native AUDIO."""
    import av
    import torch

    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise InvalidMedia("Reference audio contains no audio stream.")
        stream = container.streams.audio[0]
        sample_rate = stream.codec_context.sample_rate
        channels = stream.channels
        frames = []
        for frame in container.decode(streams=stream.index):
            buffer = torch.from_numpy(frame.to_ndarray())
            if buffer.shape[0] != channels:
                buffer = buffer.reshape(-1, channels).t()
            frames.append(buffer)
    if not frames:
        raise InvalidMedia("Reference audio contains no decodable frames.")
    waveform = _float32_pcm(torch.cat(frames, dim=1))
    return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}

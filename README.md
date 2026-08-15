# H3 Character Ref Builder

H3 Character Ref Builder is a ComfyUI custom node for managing reusable character reference profiles. A workflow selects one saved character and receives that profile's two reference images and reference audio as native ComfyUI values.

V1 is intentionally focused: it does not support video, VLM analysis, automatic reference selection, prompt generation, or prompt enhancement.

## Features

- Browser-based Character Manager served by the existing ComfyUI server at `/character-manager`
- Create, rename, describe, and delete character profiles
- Upload, replace, preview, and drag/drop two images plus one audio reference
- Stable UUID workflow values, with human-readable character names in the node dropdown
- Dynamic dropdown refresh when a node is created and when the ComfyUI window regains focus
- Native `IMAGE`, `IMAGE`, and `AUDIO` outputs
- Content-based cache invalidation for profile metadata and all three media files
- Filesystem storage beneath ComfyUI's configured user directory

## Installation

From the ComfyUI custom nodes directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/b1naryv1k1ng/h3-character-ref-builder.git
```

Restart ComfyUI after cloning.

This project adds no Python runtime dependencies. It uses Pillow, PyTorch, and PyAV from a normal current ComfyUI installation.

## Usage

1. In ComfyUI, open **Extensions → H3 Character Ref Builder → H3 Character Manager**. The same action is available from an H3 node's context menu as a compatibility fallback.
2. Select **New Character**.
3. Enter a name and, optionally, a character description.
4. Assign Reference Image 1 and Reference Image 2.
5. Assign Reference Audio.
6. Select **Save Character**.
7. Add **H3 Character Reference** from **H3 → Reference** to a workflow.
8. Select the character in the node's **Character** dropdown.
9. Connect `image_1`, `image_2`, and `audio` to downstream nodes.

The browser displays character names, but workflow JSON stores each character's immutable UUID. Renaming a character therefore does not break existing workflows. If a selected UUID is deleted, execution reports that the profile no longer exists rather than silently selecting another character.

## Supported media

Images:

- PNG
- JPEG/JPG
- WebP

Audio:

- WAV
- MP3
- FLAC
- M4A
- OGG
- AAC

Audio support follows the codecs available through the PyAV/FFmpeg stack bundled with the user's ComfyUI installation. WAV support is required and available in a normal installation. Files are preserved as uploaded and are not transcoded.

## Data storage

Profiles and media are not written into this repository. The extension resolves ComfyUI's configured user directory with `folder_paths.get_user_directory()` and stores data conceptually as:

```text
<ComfyUI user directory>/
└── h3-character-ref-builder/
    └── characters/
        └── <character UUID>/
            ├── profile.json
            ├── reference_image_1.<ext>
            ├── reference_image_2.<ext>
            └── reference_audio.<ext>
```

Each `profile.json` has schema version 1:

```json
{
  "schema_version": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Ari",
  "description": "",
  "reference_image_1": "reference_image_1.png",
  "reference_image_2": "reference_image_2.webp",
  "reference_audio": "reference_audio.wav"
}
```

Profile JSON writes use a temporary file followed by an atomic replace. Replacing a media file removes an obsolete previous extension after the profile has been updated.

## HTTP API

The manager uses a small API on the existing ComfyUI server:

```text
GET    /api/h3-character-ref-builder/characters
GET    /api/h3-character-ref-builder/characters/{id}
POST   /api/h3-character-ref-builder/characters
PUT    /api/h3-character-ref-builder/characters/{id}
DELETE /api/h3-character-ref-builder/characters/{id}
POST   /api/h3-character-ref-builder/characters/{id}/media
GET    /api/h3-character-ref-builder/characters/{id}/media/{slot}
```

Media upload is multipart form data with a `slot` field and a `file` field. Allowed slots are `reference_image_1`, `reference_image_2`, and `reference_audio`. Responses use the shape `{"ok": true, "data": ...}` or `{"ok": false, "error": {"message": "..."}}`.

UUIDs, media slots, profile filenames, extensions, and uploaded content are validated before path use. The media serving endpoint resolves only the three managed slots and is not a general filesystem route.

## Cache behavior

The node's ComfyUI `IS_CHANGED` fingerprint hashes the selected profile JSON and the contents of its two images and audio file. Updating the selected profile's name, description, or any media causes that node to execute again without a restart or manual cache clear. Editing an unrelated character does not affect the selected profile's fingerprint.

## Tests

The storage and media tests do not use the real ComfyUI user directory:

```bash
python -m pytest
```

The suite covers UUID generation, sorted listing, duplicate names, rename/description updates, deletion, media slot and path validation, replacement cleanup, corrupt/missing profiles, selected-profile cache fingerprints, and native media helper shapes when the relevant ComfyUI dependencies are present.

## License

Apache-2.0. See [LICENSE](LICENSE).

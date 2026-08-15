# H3 Character Ref Builder

H3 Character Ref Builder is a ComfyUI custom node for organizing reusable character reference libraries. Each character can keep multiple labeled image and audio references while a workflow receives only that character's two active images and one active audio reference.

This feature is for organization. The extension does not inspect prompts, automatically choose references, generate H3 prompts, use AI/VLM/LLM features, or support video.

## Features

- Browser-based Character Manager served by ComfyUI at `/character-manager`
- Up to 9 saved image references and 3 saved audio references per character
- Editable labels, image previews, audio playback, replacement, and deletion
- Explicit `Image 1`, `Image 2`, and `Active Audio` selections
- Immutable character and media UUIDs, independent of filenames and array positions
- Stable replacement: changing a reference's file or extension preserves its media UUID
- Clear generation-readiness status for incomplete profiles
- Compact ComfyUI node with exactly `IMAGE`, `IMAGE`, and `AUDIO` outputs
- Selected-output cache invalidation that ignores unused references and other characters
- Automatic, safe migration of existing schema-V1 characters
- Filesystem storage beneath ComfyUI's configured user directory

## Installation

From the ComfyUI custom nodes directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/b1naryv1k1ng/h3-character-ref-builder.git
```

Restart ComfyUI after cloning or updating.

This project adds no Python runtime dependencies. It uses Pillow, PyTorch, and PyAV from a normal current ComfyUI installation.

## Usage

1. In ComfyUI, open **Extensions → H3 Character Ref Builder → H3 Character Manager**. An H3 node context-menu action is also available as a compatibility fallback.
2. Create or select a character and save its name before adding references.
3. Add up to nine images and three audio clips. Give each reference a descriptive label.
4. Select two different images as **Image 1** and **Image 2**.
5. Select one clip as **Active Audio**.
6. Save the character. The readiness banner confirms when all three defaults are valid.
7. Add **H3 Character Reference** from **H3 → Reference** to a workflow.
8. Select the character and connect `image_1`, `image_2`, and `audio` downstream.

The manager allows incomplete characters for gradual setup, but the node will give a useful execution error until two images and one audio reference are selected. Deleting an active reference clears that default; the extension never silently substitutes a different reference.

The browser shows character names, but workflow JSON stores each character's immutable UUID. Renaming a character therefore does not break workflows. If a selected character is deleted, execution reports that it no longer exists instead of selecting another profile.

## Node contract

The node intentionally remains compact:

```text
H3 Character Reference

Character: Ari

image_1  IMAGE
image_2  IMAGE
audio    AUDIO
```

At execution time it resolves `defaults.image_1`, `defaults.image_2`, and `defaults.audio` to media records by UUID, loads those files, and emits native ComfyUI values. It never relies on collection order and does not expose every library item as a node output.

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

Audio support follows the codecs available through the PyAV/FFmpeg stack bundled with the user's ComfyUI installation. WAV is supported in a normal installation. Files retain their supported upload extension and are not transcoded.

## Data storage and schema

Profiles and media are not written into this repository. The extension uses `folder_paths.get_user_directory()` and stores data as:

```text
<ComfyUI user directory>/
└── h3-character-ref-builder/
    └── characters/
        └── <character UUID>/
            ├── profile.json
            ├── images/
            │   ├── <media UUID>.png
            │   └── <media UUID>.jpg
            └── audio/
                └── <media UUID>.wav
```

Schema version 2 uses immutable media IDs and UUID-based defaults:

```json
{
  "schema_version": 2,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Ari",
  "description": "",
  "images": [
    {
      "id": "11111111-1111-4111-8111-111111111111",
      "file": "images/11111111-1111-4111-8111-111111111111.png",
      "label": "Front portrait"
    },
    {
      "id": "22222222-2222-4222-8222-222222222222",
      "file": "images/22222222-2222-4222-8222-222222222222.webp",
      "label": "Full body"
    }
  ],
  "audio": [
    {
      "id": "33333333-3333-4333-8333-333333333333",
      "file": "audio/33333333-3333-4333-8333-333333333333.wav",
      "label": "Neutral voice"
    }
  ],
  "defaults": {
    "image_1": "11111111-1111-4111-8111-111111111111",
    "image_2": "22222222-2222-4222-8222-222222222222",
    "audio": "33333333-3333-4333-8333-333333333333"
  }
}
```

Profile JSON writes use a temporary file, flush it to disk, and atomically replace the prior profile. Media replacement writes and validates the new file before updating the profile; if the extension changed, the obsolete file is removed only after the profile update succeeds.

## Migration from schema V1

Existing V1 profiles migrate automatically the first time they are read. The migration:

- copies `reference_image_1`, `reference_image_2`, and `reference_audio` into UUID-addressed V2 library files;
- preserves their old roles in `defaults.image_1`, `defaults.image_2`, and `defaults.audio`;
- uses deterministic media UUIDs so retrying is idempotent;
- validates the copied media and atomically writes the V2 profile before deleting legacy files; and
- cleans up partial copies and leaves the original V1 profile/media intact if migration fails.

Existing workflow character UUIDs remain unchanged, so migrated workflows resolve the same two images and audio as before.

## HTTP API

The manager uses a namespaced API on ComfyUI's existing server:

```text
GET    /api/h3-character-ref-builder/characters
GET    /api/h3-character-ref-builder/characters/{character_id}
POST   /api/h3-character-ref-builder/characters
PUT    /api/h3-character-ref-builder/characters/{character_id}
DELETE /api/h3-character-ref-builder/characters/{character_id}

POST   /api/h3-character-ref-builder/characters/{character_id}/media
GET    /api/h3-character-ref-builder/characters/{character_id}/media/{media_id}
PUT    /api/h3-character-ref-builder/characters/{character_id}/media/{media_id}
DELETE /api/h3-character-ref-builder/characters/{character_id}/media/{media_id}

PUT    /api/h3-character-ref-builder/characters/{character_id}/defaults
```

Creating media uses multipart form data with `type` (`image` or `audio`), optional `label`, and `file`. Updating media accepts JSON containing only `label`, or multipart data containing an optional `label` and/or replacement `file`. Replacing a file retains the media UUID even when its extension changes.

The defaults request contains exactly `image_1`, `image_2`, and `audio`, whose values are media UUIDs or `null`. Responses use `{"ok": true, "data": ...}` or `{"ok": false, "error": {"message": "..."}}`.

Character UUIDs, media UUIDs, media ownership, type, collection limits, filenames, extensions, default-slot types, and uploaded content are validated. The preview endpoint resolves only UUID-addressed media belonging to the requested character and never accepts an arbitrary filesystem path.

## Cache behavior

The node's `IS_CHANGED` fingerprint includes the selected character's name and description, the three default media UUIDs, and the contents and paths of only those selected files. It changes when a selected file is replaced, a default selection changes, or relevant selected-profile metadata changes. Relabeling or replacing an unused reference does not invalidate the current outputs, and modifying another character does not affect this node.

## Tests

The tests use temporary storage rather than the real ComfyUI user directory:

```bash
python -m pytest
```

The suite covers V1 migration and idempotence, UUID identity, image/audio limits, label and replacement behavior, obsolete-extension cleanup, deletion and default clearing, default type validation, incomplete-profile errors, UUID-based node resolution, the exact node output contract, selected-output fingerprints, malformed profiles, path traversal protection, and the HTTP media/default API. Native tensor/audio loader tests run when the corresponding ComfyUI dependencies are installed.

## License

Apache-2.0. See [LICENSE](LICENSE).

# H3 Character Ref Builder

H3 Character Ref Builder is a ComfyUI custom node for organizing reusable character references, reusable Scene Presets, and deterministic MiniMax H3 Ref2VA prompts.

Pick a character, pick an optional environment, describe what happens, and the node emits the active two images, active audio reference, and a complete six-section H3 prompt.

V3.1 performs deterministic text assembly only. It does not use an LLM, VLM, external AI API, prompt rewriting, image analysis, automatic reference selection, scene generation, or video references.

## Features

- One browser-based **H3 Reference Manager** at `/character-manager`
- **Characters** and **Scene Presets** tabs in the existing dark manager UI
- Up to 9 labeled image references and 3 labeled audio references per character
- Immutable character, media, and scene UUIDs
- Two active image defaults and one active audio default per generation
- A semantic role on every reference for deterministic prompt construction
- Image previews, audio playback, replacement, deletion, and drag/drop upload
- Independent reusable environment definitions and default soundscapes selected as `<Subject 2>`
- Compact ComfyUI node with `image_1`, `image_2`, `audio`, and `prompt` outputs
- Selected-output/prompt cache invalidation isolated from unused references and unrelated scenes
- Automatic safe migration from V1/V2 character profiles and V1 Scene Presets

## Installation

From the ComfyUI custom nodes directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/b1naryv1k1ng/h3-character-ref-builder.git
```

Restart ComfyUI after cloning or updating. The project adds no Python runtime dependencies; it uses Pillow, PyTorch, and PyAV from a normal current ComfyUI installation.

## V3.1 workflow

1. Open **Extensions → H3 Character Ref Builder → H3 Reference Manager**.
2. In **Characters**, create or select a character and maintain its reference library.
3. Give each active reference the semantic role it contributes.
4. Select two different images as **Image 1** and **Image 2**, plus one **Active Audio** reference.
5. Optionally create reusable environments and their baseline ambience under **Scene Presets**.
6. Add **H3 Character Reference** from **H3 → Reference** to a workflow.
7. Pick a Character and optional Scene Preset, then enter **Video / Action Description**.
8. Optionally enter action-specific sounds in **Additional Soundscape** and customize **Non-Diegetic Music**.
9. Connect `image_1`, `image_2`, and `audio` to the H3 reference inputs.
10. Connect `prompt` to the MiniMax H3 prompt input.

The node does not rewrite or enhance the action description. It trims surrounding whitespace, places the text under `detailed_description`, and adds `[Shot 1]` only when the user has not already supplied it.

## Character reference libraries

Each character can store up to nine images and three audio clips. References have user-editable labels and immutable media UUIDs. Replacing a file preserves that UUID even when its extension changes.

The node outputs only the selected defaults:

```text
IMAGE  image_1
IMAGE  image_2
AUDIO  audio
STRING prompt
```

The first three outputs retain their original positions for existing workflows. Defaults are resolved by media UUID, never by collection order.

### Image roles

| Stored role | Manager label | Prompt contribution |
|---|---|---|
| `face_identity` | Face / Identity | Facial identity, structure, eyes, hair, and recognizable facial detail |
| `full_body_identity` | Full Body / Physical Identity | Full-body identity, body proportions, build, silhouette, skin tone, and distinctive physical details; source wardrobe is not preserved |
| `alternate_identity` | Alternate Identity Angle | Additional identity, anatomy, and alternate-angle detail |
| `wardrobe` | Wardrobe / Clothing | Wardrobe, clothing details, colors, and accessories |
| `pose_orientation` | Pose / Orientation | Body orientation and pose only; not source background, lighting, or framing |
| `expression` | Expression | Facial expression and performance only; not source background, lighting, or framing |
| `general` | General Reference | Additional appearance detail |

Only the two active image defaults contribute to `<Subject 1>`. They are complementary references for one character, not separate subjects. Full Body / Physical Identity defines the person's body, while Wardrobe / Clothing is the separate role that intentionally contributes clothing.

### Audio roles

| Stored role | Manager label | Prompt contribution |
|---|---|---|
| `voice_identity` | Voice Identity | Voice timbre, accent, pacing, and delivery |
| `delivery_emotion` | Delivery / Emotion | Vocal tone, emotion, intensity, and pacing |
| `general` | General Audio Reference | General vocal characteristics and delivery |

Character audio is always an H3 audio reference. Generated retention uses `<Audio 1>: reference`; it never uses `fully_preserved` for audio and explicitly says not to copy the source signal, dialogue, or words.

### Character Identity Details

The optional character description is presented as **Character Identity Details** and is appended as stable user-authored information inside `<Subject 1>`. The manager/store removes a pasted leading `<Subject 1> is` prefix to avoid duplicated syntax. It does not infer characteristics from files, labels, or images.

## Scene Presets

Scene Presets are independent reusable environments managed in the second tab. Each has an immutable UUID, editable name, multiline **Scene Definition**, and optional multiline **Default Soundscape**. Renaming does not break workflows because the node stores the UUID.

When selected, the stored definition becomes:

```text
<Subject 2> is {scene definition}
```

The definition is preserved except for surrounding whitespace. A pasted leading `<Subject 2> is` prefix is removed on save. No presets are seeded automatically.

The **Scene Default Soundscape** describes sounds normally inherent to the environment. The node's **Additional Soundscape** describes sounds caused by this particular generation or action. The prompt uses both in that order without rewriting either value. If only one is present, it uses that value; if neither is present, it uses the generic natural-ambience fallback.

The node's three multiline authoring fields are permanently labelled **Video / Action Description**, **Additional Soundscape**, and **Non-Diegetic Music**. The serialized key for Additional Soundscape remains `overall_soundscape` so existing workflows continue to load.

The stable `(No Scene Preset)` option omits `<Subject 2>` from subject definitions, summary, and retention analysis. Additional Soundscape still works without a scene. A deleted UUID produces an explicit missing-scene error rather than silently choosing another preset.

## Deterministic Ref2VA prompt builder

Every generated prompt contains exactly these sections in order:

```text
subject_definitions:

summary:

retention_analysis:

detailed_description:

overall_soundscape:

non_diegetic_music:
```

`subject_definitions` combines the two active image roles into one `<Subject 1>`, defines `<Audio 1>` from the active audio role, and adds the selected scene as `<Subject 2>`. The short summary begins with `[reference generation + audio reference]`. The user action appears only in `detailed_description`.

When neither a Scene Default Soundscape nor an Additional Soundscape is available, the fallback is:

```text
Natural diegetic ambience appropriate to the scene, with synchronized physical sounds caused by the visible action.
```

Non-diegetic music defaults to `N/A`; music is never inferred.

## Supported media

Images: PNG, JPEG/JPG, and WebP.

Audio: WAV, MP3, FLAC, M4A, OGG, and AAC. Codec support follows the PyAV/FFmpeg stack bundled with ComfyUI. Files retain supported upload extensions and are not transcoded.

## Storage and schemas

Data lives beneath `folder_paths.get_user_directory()`:

```text
<ComfyUI user directory>/
└── h3-character-ref-builder/
    ├── characters/
    │   └── <character UUID>/
    │       ├── profile.json
    │       ├── images/<media UUID>.<ext>
    │       └── audio/<media UUID>.<ext>
    └── scenes/
        └── <scene UUID>/
            └── scene.json
```

Character schema V3 adds `role` to each V2 media record while retaining character/media UUIDs, labels, paths, defaults, and description. Scene schema V2 stores `schema_version`, `id`, `name`, `definition`, and optional `default_soundscape`.

All JSON writes use a temporary file, flush it to disk, and atomically replace the prior file. UUIDs, ownership, roles, media types, limits, filenames, content, and paths are validated before use.

### Migration

Existing V2 profiles migrate automatically on first read without renaming or moving media:

- active Image 1 → `face_identity`
- active Image 2 → `full_body_identity`
- active Audio → `voice_identity`
- unused images/audio → `general`

An already present valid role is preserved. The update is atomic and idempotent.

V1 profiles still migrate safely into the UUID-addressed library. Their original two images and audio retain the same default behavior and receive the corresponding V3 roles. Legacy files are deleted only after copied media validates and the new profile is atomically written.

Scene schema V1 presets migrate automatically on first read. Their UUID, name, and definition are preserved, `default_soundscape` is initialized to an empty string, and the atomic migration is idempotent.

## HTTP API

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

GET    /api/h3-character-ref-builder/scenes
GET    /api/h3-character-ref-builder/scenes/{scene_id}
POST   /api/h3-character-ref-builder/scenes
PUT    /api/h3-character-ref-builder/scenes/{scene_id}
DELETE /api/h3-character-ref-builder/scenes/{scene_id}
```

Media creation accepts multipart `type`, `label`, `role`, and `file`. Media updates accept JSON `label` and/or `role`, or multipart metadata plus an optional replacement file. Scene create/update operations accept `name`, `definition`, and `default_soundscape`; list responses contain only UUID and name, while detail responses include both multiline fields.

Responses use `{"ok": true, "data": ...}` or `{"ok": false, "error": {"message": "..."}}`. Preview routes resolve only media UUIDs belonging to the requested character and never accept arbitrary filesystem paths.

## Cache behavior

The node fingerprint includes selected files, selected media UUIDs and roles, defaults, Character Identity Details, selected scene UUID, definition, default soundscape, and the node's prompt-authoring fields. It deliberately excludes unused media, media labels, character names, scene names, unrelated characters, and unrelated scenes where those values cannot affect outputs or prompt text.

## Tests

```bash
python -m pytest
```

The suite covers character and scene migration, role validation and UUID stability, media limits and replacement, Scene Preset CRUD/security, exact prompt structure and role semantics, soundscape composition, UUID-based node resolution, API behavior, permanent node labels, and prompt-aware cache isolation. Native tensor/audio loader tests run when the relevant ComfyUI dependencies are installed.

## License

Apache-2.0. See [LICENSE](LICENSE).

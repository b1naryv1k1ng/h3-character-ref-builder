# H3 Character Ref Builder

H3 Character Ref Builder is a ComfyUI custom-node pack for reusable character
references, Scene Presets, deterministic H3 context construction, and optional
OpenAI-compatible action enhancement.

The workflow uses one of two reference nodes plus one shared enhancer:

1. **H3 Character Reference** loads one character, while **H3 Dual Character Reference**
   loads two independent characters. Both emit deterministic, versioned
   `character_context` JSON.
2. **H3 Prompt Enhancer** accepts context from either reference node, asks an
   OpenAI-compatible model only for action choreography and action-specific sounds, then
   assembles the final six-section H3 Ref2VA prompt.

The Character Manager, UUID-addressed media library, reference roles, and Scene Preset
storage remain local and deterministic.

## Features

- Browser-based **H3 Reference Manager** at `/character-manager`
- Compact Character Manager button in the ComfyUI top bar
- Up to 9 labeled image references and 3 labeled audio references per character
- Immutable character, media, and scene UUIDs
- Two active image defaults and one active audio default per generation
- Semantic image/audio roles for deterministic subject and retention text
- Separate single- and dual-character reference nodes using the same managed libraries
- Independent Scene Presets with definitions, baseline soundscapes, and one optional managed reference image
- Reusable single-image Prop References with deterministic names and optional descriptions
- Human-inspectable, versioned `character_context` JSON with no media paths or bytes
- Provider-agnostic OpenAI-compatible chat-completions client
- Strict structured-output request with a JSON-only compatibility fallback
- Bounded in-process enhancement cache that avoids unnecessary paid API calls
- Automatic safe migration from V1/V2 character profiles and V1/V2 Scene Presets

## Installation

From the ComfyUI custom nodes directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/b1naryv1k1ng/h3-character-ref-builder.git
```

Restart ComfyUI after cloning or updating. No OpenAI SDK is required. The enhancer uses
Python's standard-library HTTP client; media loading uses the libraries already bundled
with a normal current ComfyUI installation.

## Prompt enhancer configuration

Open ComfyUI **Settings → H3 Character Ref Builder → Prompt Enhancer** to configure:

- API Base URL (default `https://api.venice.ai/api/v1`)
- API Model (default `olafangensan-glm-4.7-flash-heretic`)
- Request Timeout (integer seconds, 1–300; default 60)
- API Key

The API key control is write-only. Settings shows whether a saved or environment key is
available, but the backend never returns the credential and the field is never
repopulated. Saved provider configuration lives at
`<ComfyUI user directory>/h3-character-ref-builder/prompt-enhancer-config.json`,
is written atomically, and is read for each execution so changes do not require a
ComfyUI restart.

Environment variables remain fallback configuration:

| Variable | Purpose |
|---|---|
| `H3_PROMPT_ENHANCER_API_KEY` | Provider credential |
| `H3_PROMPT_ENHANCER_BASE_URL` | OpenAI-compatible API base URL |
| `H3_PROMPT_ENHANCER_MODEL` | Provider model identifier |
| `H3_PROMPT_ENHANCER_TIMEOUT_SECONDS` | Integer request timeout from 1–300 seconds |

Precedence is saved configuration, then environment, then built-in defaults where
applicable. An environment API key is never copied into the saved file. If the base URL
does not already end in `/chat/completions`, that path is appended. Never paste an API
key into a workflow, node widget, Scene Preset, or Character Manager field.

## Workflow

1. Open the **H3 Reference Manager** from the top bar or at `/character-manager`.
2. Create/select a character, maintain its references, and select two active images plus
   one active audio reference.
3. Optionally create and select a Scene Preset with a raw environment definition and
   baseline soundscape. A Scene Preset can also hold one optional environment image.
4. Optionally create a Prop Reference with its single required image.
5. Add **H3 Character Reference** for one character or **H3 Dual Character Reference**
   for two independently referenced characters from **H3 → Reference**. Select optional
   scene and prop references on that node.
6. Connect each emitted character image/audio output and any real `scene_image` or
   `prop_image` to the corresponding H3 reference inputs.
7. Add the single shared **H3 Prompt Enhancer** from **H3 → Prompt**.
8. Connect `character_context` from either reference node to the enhancer.
9. Enter a duration, editable System Prompt, rough Action Idea, optional Additional
   Notes, and music.
10. Connect the enhancer's `prompt` output to the MiniMax H3 prompt input.

The two inspection outputs expose exactly the structured action fields used during final
assembly: `detailed_description` and `additional_soundscape`.

## H3 Character Reference

Inputs:

```text
Character     selected character UUID
Scene Preset  selected scene UUID or (No Scene Preset)
Prop Reference selected prop UUID or (No Prop Reference)
```

Outputs:

```text
1  IMAGE   character_image_1
2  IMAGE   character_image_2
3  AUDIO   audio
4  STRING  character_context
5  IMAGE   scene_image
6  IMAGE   prop_image
```

The original first four slot positions remain unchanged for saved-workflow compatibility;
only the first two visible names changed. In single-character mode, `<Subject 1>` is the
character and `<Subject 2>` is the environment when a scene exists. `scene_image` is
appended in slot 5 and is the optional `<Picture 3>` environment reference. When the
selected scene is text-only (or no scene is selected), this output is `None`; no synthetic
placeholder image is created. `prop_image` is appended in slot 6 and likewise returns
`None` when no prop is selected.

## H3 Dual Character Reference

This separate node selects two independent profiles from the same Character library plus
the same optional Scene Preset and Prop Reference libraries. Selecting the same profile
twice is allowed. Its inputs are:

```text
Character 1    selected character UUID
Character 2    selected character UUID
Scene Preset   selected scene UUID or (No Scene Preset)
Prop Reference selected prop UUID or (No Prop Reference)
```

Its outputs are:

```text
1  IMAGE   character_1_image_1
2  IMAGE   character_1_image_2
3  AUDIO   character_1_audio
4  IMAGE   character_2_image_1
5  IMAGE   character_2_image_2
6  AUDIO   character_2_audio
7  STRING  character_context
8  IMAGE   scene_image
9  IMAGE   prop_image
```

Dual-character numbering is exact and gap-free:

- Character 1 is `<Subject 1>` using `<Picture 1>`, `<Picture 2>`, and `<Audio 1>`.
- Character 2 is `<Subject 2>` using `<Picture 3>`, `<Picture 4>`, and `<Audio 2>`.
- A selected scene is `<Subject 3>`. Its real image is `<Picture 5>`; a text-only scene
  consumes no Picture slot.
- A prop is `<Picture 6>` when a real scene image occupies Picture 5, otherwise it is
  `<Picture 5>`. Props remain Picture references and never become Subjects.

Absent scene and prop outputs are `None`, never placeholders. Both reference nodes feed
the same H3 Prompt Enhancer.

### Character context schema V2

```json
{
  "schema_version": 2,
  "subject_roles": {
    "<Subject 1>": {"type": "character", "name": "Ashley"},
    "<Subject 2>": {"type": "character", "name": "Vespera"},
    "<Subject 3>": {"type": "environment", "name": "Beanbag"}
  },
  "subject_definitions": "...",
  "summary": "...",
  "retention_analysis": "...",
  "scene_definition": "...",
  "default_soundscape": "..."
}
```

`subject_roles` is structured, authoritative metadata mapping each Subject token to a
saved character or environment name. Single mode uses Subject 1 for the character and
Subject 2 for an optional environment. Dual mode uses Subjects 1 and 2 for the two
characters and Subject 3 for an optional environment. Schema-v1 contexts remain accepted
and are normalized to schema v2 with empty legacy names.

`scene_definition` is the raw selected Scene Preset definition body and
`default_soundscape` is its baseline ambience. Visual scenes use the mode-specific Picture
number and treat saved scene text as supplemental detail. Scene images are sent to H3 only;
they are never sent to the prompt-enhancement provider.

### Prop References

Prop References are an independent reusable library, not part of characters or Scene
Presets. Each prop has a UUID, a required deterministic name, an optional description,
and exactly one managed image. The manager may temporarily hold a newly created prop
without an image so the two-step upload can complete; incomplete props are clearly
marked and are not offered in the node selector.

Only one prop can be selected on either H3 reference node. Its name is used as the
deterministic noun and its optional description is supplemental visual information. The
generated context describes the selected picture as the visual reference for that prop
while explicitly excluding background, lighting, framing, surrounding people/body
parts, pose, and unrelated content. It never assigns the prop to a subject or implies
ownership.

Picture numbering follows the actual connected image outputs:

- With a real Scene Preset image: scene is `<Picture 3>` and prop is `<Picture 4>`.
- Without a real scene image (including a text-only Scene Preset): prop is `<Picture 3>`.

The selected prop's deterministic definition and retention guidance are included in
`character_context`, but neither the prop metadata nor image is sent to the prompt
enhancement provider. Connect `prop_image` to the matching H3 picture input. With no
selection, slot 6 is `None`; no placeholder is generated.

The context contains saved Subject names for choreography mapping, but no image bytes,
audio bytes, file paths, media labels, filenames, or other media storage details.

## H3 Prompt Enhancer

Inputs:

```text
STRING  character_context   connection from either H3 reference node
INT     duration_seconds    default 15, range 1–60
STRING  system_prompt       multiline workflow-owned provider instructions
STRING  action_idea         multiline rough action request
STRING  additional_notes    multiline, default empty
STRING  non_diegetic_music  multiline, default N/A
```

Outputs:

```text
STRING  prompt
STRING  detailed_description
STRING  additional_soundscape
```

The exact `system_prompt` widget value is sent as the OpenAI-compatible `system`
message and is saved normally in the workflow. It is not added to the user message and
no hidden instructions are prepended or appended. The normal multiline widget can be
converted to a connected STRING input through ComfyUI's widget-to-input action. Blank
or whitespace-only values fail validation.

Only `subject_roles`, duration, action idea, raw scene definition, Scene Preset
`default_soundscape`, and additional notes are sent as the JSON user message. Images,
audio, deterministic subject boilerplate, retention text, completed prompts, and the
system prompt are not concatenated into that user message. The baseline soundscape is
provided so the model can return only action-specific diegetic sounds that are not
already covered by the scene ambience.

Workflow-owned system prompts should treat `subject_roles` as authoritative: never
hardcode that Subject 2 is always the environment, never reassign tokens, map matching
action-idea names to their declared Subject token, and never make an environment Subject
perform human actions. The prompt must ask for the structured `beats` and
`additional_soundscape` contract described below, not final H3 formatting. These
instructions remain workflow-editable and are not silently inserted by Python.

### Structured provider response

The enhancer first requests this strict JSON-schema shape:

```json
{
  "beats": [
    {
      "start_seconds": 0,
      "end_seconds": 4,
      "description": "<Subject 1> crosses the room as the camera tracks beside them.",
      "vocal_events": [
        {
          "kind": "dialogue",
          "subject": "<Subject 1>",
          "language": "English",
          "delivery": "quietly",
          "content": "Come over here."
        }
      ]
    },
    {
      "start_seconds": 4,
      "end_seconds": 8,
      "description": "<Subject 1> stops beside the table.",
      "vocal_events": []
    }
  ],
  "additional_soundscape": "Footsteps crossing the floor."
}
```

Beat count and integer boundaries are semantic model decisions rather than fixed or
equal divisions. Python requires at least one contiguous beat covering exactly the
requested duration and enforces a safety ceiling of `min(duration_seconds, 12)` beats.
Descriptions contain visible action/camera choreography only. Dialogue and nonverbal
vocalizations are ordered separately in each beat's `vocal_events` array.

Python validates and safely normalizes Subject tokens, then compiles the plan into H3
syntax. It generates `[Shot 1]` and timestamps, assigns `(S1)`, `(S2)`, and later IDs by
first actual dialogue order, and formats dialogue `<d>` tags. Vocalizations receive
neither a speaker ID nor a dialogue tag. For example, the response above compiles to:

```text
[Shot 1]

00:00-00:04
<Subject 1> crosses the room as the camera tracks beside them.
<Subject 1> (S1) says quietly: <d>[English] Come over here.</d>

00:04-00:08
<Subject 1> stops beside the table.
```

`additional_soundscape` may be empty and contains only additional diegetic sound caused
by the requested action; it should not repeat baseline ambience or spoken dialogue. If
a compatible provider rejects strict `response_format` with HTTP 400/422, the client
retries without it while retaining the exact workflow-supplied system message. Plain
JSON, provider `parsed` objects, and accidental fenced JSON blocks are accepted. An
invalid semantic plan receives one corrective provider retry with the validation reason.
If that response is also invalid, the node fails clearly and caches nothing.

## Final prompt assembly

The enhancer emits exactly these top-level sections in order:

```text
subject_definitions:

summary:

retention_analysis:

detailed_description:

overall_soundscape:

non_diegetic_music:
```

The first three are copied from `character_context`; the LLM cannot rewrite them.
`detailed_description` is deterministically compiled by Python from the structured
semantic timeline.

When baseline ambience and action-specific sounds both exist, they are joined with
normal whitespace inside the sole soundscape section:

```text
<Scene Preset baseline soundscape> <LLM-generated sounds>
```

If only one exists, it is used without extra formatting. If neither exists, the original
fallback remains:

```text
Natural diegetic ambience appropriate to the scene, with synchronized physical sounds caused by the visible action.
```

Music is copied from the widget and falls back to `N/A` when blank.

## Execution behavior

Both reference nodes fingerprint only selected profiles and selected scene/prop state.
The dual node independently includes Character 1 and Character 2 fingerprints. Selected
character identity details, names, active media, media roles or contents; selected scene
name, text, soundscape or image; and selected prop name, description or image invalidate
the relevant node. Unrelated characters, scenes, props, unused references, and media
labels do not.

The **H3 Prompt Enhancer** is intentionally non-cacheable. Every queued execution performs
a fresh provider request so changes to connected prompts and choreography are always
evaluated by the LLM. Repeated identical queues also make fresh provider calls.

## Existing workflow migration

The `H3CharacterReference` node type and all four prior output positions are retained;
the optional scene image and prop image were appended as outputs 5 and 6.
Its Python execution methods accept and ignore legacy prompt-authoring arguments where
ComfyUI supplies them by name or position. The three obsolete widgets are no longer
declared for new nodes.

This interface change is intentional: the fourth output now contains context JSON, not a
completed prompt. Existing workflows must add **H3 Prompt Enhancer**, reconnect the
fourth output through it, and move their action/music authoring into the new node.
Depending on the ComfyUI frontend version, recreating an old Character Reference node
may be necessary to discard serialized legacy widget values cleanly. Existing
`character_context` schema-v1 strings remain accepted by H3 Prompt Enhancer and normalize
to schema v2 role metadata, preserving saved Reference → Enhancer workflows.

## Storage and media behavior

Data remains beneath `folder_paths.get_user_directory()`:

```text
<ComfyUI user directory>/h3-character-ref-builder/
├── characters/<character UUID>/
│   ├── profile.json
│   ├── images/<media UUID>.<ext>
│   └── audio/<media UUID>.<ext>
├── scenes/<scene UUID>/
│   ├── scene.json
│   └── images/<scene-image UUID>.<ext>  (optional)
├── props/<prop UUID>/
│   ├── prop.json
│   └── images/<prop-image UUID>.<ext>
└── prompt-enhancer-config.json
```

Scene schema V3 adds nullable `reference_image` metadata. Existing V1/V2 scenes migrate
atomically and idempotently with `reference_image: null`; names, definitions, and default
soundscapes are preserved. Uploaded files receive UUID-backed managed filenames, use the
same validation as character images, and are cleaned up on replacement, removal, or scene
deletion. Supported images remain PNG, JPEG/JPG, and WebP; supported audio remains WAV,
MP3, FLAC, M4A, OGG, and AAC according to ComfyUI's PyAV/FFmpeg stack.

Prop schema V1 uses the same UUID/path/media validation and atomic metadata writes. Prop
image replacement preserves the media UUID when possible and removes the superseded file;
deleting a prop removes its managed directory.

## Tests

The suite uses mocked HTTP calls and never contacts a real provider:

```bash
python -m pytest
```

Coverage includes character/scene/prop storage, migrations, route security, single/dual
context, subject-role validation, dynamic Picture/Audio numbering, exact final section order, soundscape combinations,
structured/fenced response parsing, provider authentication/rate-limit/server/network
failures, secret redaction, and enhancement cache boundaries.

## License

Apache-2.0. See [LICENSE](LICENSE).

# H3 Character Ref Builder

H3 Character Ref Builder is a ComfyUI custom-node pack for reusable character
references, Scene Presets, deterministic H3 context construction, and optional
OpenAI-compatible action enhancement.

The workflow is split between two nodes:

1. **H3 Character Reference** loads the selected media and emits deterministic,
   versioned `character_context` JSON.
2. **H3 Prompt Enhancer** asks an OpenAI-compatible model only for action choreography
   and action-specific sounds, then assembles the final six-section H3 Ref2VA prompt.

The Character Manager, UUID-addressed media library, reference roles, and Scene Preset
storage remain local and deterministic.

## Features

- Browser-based **H3 Reference Manager** at `/character-manager`
- Compact Character Manager button in the ComfyUI top bar
- Up to 9 labeled image references and 3 labeled audio references per character
- Immutable character, media, and scene UUIDs
- Two active image defaults and one active audio default per generation
- Semantic image/audio roles for deterministic subject and retention text
- Independent Scene Presets with definitions and baseline soundscapes
- Human-inspectable, versioned `character_context` JSON with no media paths or bytes
- Provider-agnostic OpenAI-compatible chat-completions client
- Strict structured-output request with a JSON-only compatibility fallback
- Bounded in-process enhancement cache that avoids unnecessary paid API calls
- Automatic safe migration from V1/V2 character profiles and V1 Scene Presets

## Installation

From the ComfyUI custom nodes directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/b1naryv1k1ng/h3-character-ref-builder.git
```

Restart ComfyUI after cloning or updating. No OpenAI SDK is required. The enhancer uses
Python's standard-library HTTP client; media loading uses the libraries already bundled
with a normal current ComfyUI installation.

## Prompt enhancer server configuration

Set these environment variables on the server process that launches ComfyUI:

| Variable | Required | Purpose |
|---|---:|---|
| `H3_PROMPT_ENHANCER_API_KEY` | Yes | Provider credential; never exposed as a node widget or serialized into workflows |
| `H3_PROMPT_ENHANCER_BASE_URL` | Yes | OpenAI-compatible API base URL, such as `https://provider.example/v1` |
| `H3_PROMPT_ENHANCER_MODEL` | Unless the Model widget is filled | Default provider model identifier |
| `H3_PROMPT_ENHANCER_TIMEOUT_SECONDS` | No | Request timeout from 1–300 seconds; defaults to 60 |

If the base URL does not already end in `/chat/completions`, that path is appended.
Restart ComfyUI after changing its environment. Never paste the API key into a workflow,
node widget, Scene Preset, or Character Manager field.

## Workflow

1. Open the **H3 Reference Manager** from the top bar or at `/character-manager`.
2. Create/select a character, maintain its references, and select two active images plus
   one active audio reference.
3. Optionally create and select a Scene Preset with a raw environment definition and
   baseline soundscape.
4. Add **H3 Character Reference** from **H3 → Reference**.
5. Connect its `image_1`, `image_2`, and `audio` outputs to the H3 reference inputs.
6. Add **H3 Prompt Enhancer** from **H3 → Prompt**.
7. Connect `character_context` from the first node to the enhancer.
8. Enter a duration, rough Action Idea, optional Additional Notes, music, and model.
9. Connect the enhancer's `prompt` output to the MiniMax H3 prompt input.

The two inspection outputs expose exactly the structured action fields used during final
assembly: `detailed_description` and `additional_soundscape`.

## H3 Character Reference

Inputs:

```text
Character     selected character UUID
Scene Preset  selected scene UUID or (No Scene Preset)
```

Outputs:

```text
IMAGE   image_1
IMAGE   image_2
AUDIO   audio
STRING  character_context
```

The first three output positions and media-loading behavior are unchanged. The fourth
output is no longer a finished prompt.

### Character context schema V1

```json
{
  "schema_version": 1,
  "subject_definitions": "...",
  "summary": "...",
  "retention_analysis": "...",
  "scene_definition": "...",
  "default_soundscape": "..."
}
```

The first three fields preserve the deterministic V3.1 wording. `scene_definition` is
the raw selected Scene Preset definition body and `default_soundscape` is its baseline
ambience. With no scene, both fields are empty and `<Subject 2>` is omitted from all
deterministic sections.

The context contains no image bytes, audio bytes, file paths, media labels, character
names, or other storage details.

## H3 Prompt Enhancer

Inputs:

```text
STRING  character_context   connection from H3 Character Reference
INT     duration_seconds    default 15, range 1–60
STRING  action_idea         multiline rough action request
STRING  additional_notes    multiline, default empty
STRING  non_diegetic_music  multiline, default N/A
STRING  model               model identifier; environment-derived default
```

Outputs:

```text
STRING  prompt
STRING  detailed_description
STRING  additional_soundscape
```

Only the duration, action idea, raw scene definition, and additional notes are sent as
the user request. Images, audio, deterministic subject boilerplate, retention text,
baseline ambience, and completed prompts are not sent to the provider.

The dedicated system prompt lives in
`h3_character_ref_builder/enhancer_system_prompt.py`. Its separately declared
`SYSTEM_PROMPT_VERSION` and full content participate in cache fingerprints, so prompt
tuning invalidates stale enhancement results without changing node architecture.

### Structured provider response

The enhancer first requests this strict JSON-schema shape:

```json
{
  "detailed_description": "[Shot 1] [0-5s] ...",
  "additional_soundscape": "..."
}
```

`additional_soundscape` may be an empty string. If a compatible provider rejects the
strict `response_format` with HTTP 400/422, the client retries without that parameter
while retaining the JSON-only system instruction. Plain JSON, provider `parsed` objects,
and accidental fenced JSON blocks are accepted. Missing fields, wrong types, invalid
JSON, or a detailed description without `[Shot 1]` produce an explicit node error.

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
`detailed_description` comes from the structured LLM response.

When baseline ambience and action-specific sounds both exist, assembly is explicit:

```text
<Scene Preset baseline soundscape>

Additional action-specific sounds: <LLM-generated sounds>
```

If only one exists, it is used without an empty label. If neither exists, the original
fallback remains:

```text
Natural diegetic ambience appropriate to the scene, with synchronized physical sounds caused by the visible action.
```

Music is copied from the widget and falls back to `N/A` when blank.

## Cache behavior

**H3 Character Reference** fingerprints only the selected character/reference state and
selected Scene Preset definition/soundscape. Unused references, unrelated characters,
unrelated scenes, character names, scene names, and media labels do not invalidate it.

**H3 Prompt Enhancer** uses two cache layers:

- Its ComfyUI fingerprint covers complete final-output inputs: full context, duration,
  action, notes, music, model/base URL configuration, and system-prompt content.
- A bounded in-process paid-call cache covers only data actually affecting the LLM:
  scene definition, duration, action, notes, endpoint, model, and system prompt.

Consequently, re-queuing unchanged nodes uses normal ComfyUI caching. Changing only
music, deterministic subject text, or Scene Preset baseline ambience rebuilds the final
prompt without another API call. Changing action, duration, notes, model/provider, raw
scene definition, or system prompt causes a new enhancement request. The API key is
excluded from workflow data, fingerprints, logs, and errors.

## Existing workflow migration

The `H3CharacterReference` node type and its first three output positions are retained.
Its Python execution methods accept and ignore legacy prompt-authoring arguments where
ComfyUI supplies them by name or position. The three obsolete widgets are no longer
declared for new nodes.

This interface change is intentional: the fourth output now contains context JSON, not a
completed prompt. Existing workflows must add **H3 Prompt Enhancer**, reconnect the
fourth output through it, and move their action/music authoring into the new node.
Depending on the ComfyUI frontend version, recreating an old Character Reference node
may be necessary to discard serialized legacy widget values cleanly.

## Storage and media behavior

Data remains beneath `folder_paths.get_user_directory()`:

```text
<ComfyUI user directory>/h3-character-ref-builder/
├── characters/<character UUID>/
│   ├── profile.json
│   ├── images/<media UUID>.<ext>
│   └── audio/<media UUID>.<ext>
└── scenes/<scene UUID>/scene.json
```

Character schema V3, Scene schema V2, UUID behavior, media roles, upload validation,
atomic writes, migrations, and Character Manager APIs are unchanged. Supported images
remain PNG, JPEG/JPG, and WebP; supported audio remains WAV, MP3, FLAC, M4A, OGG, and
AAC according to ComfyUI's PyAV/FFmpeg stack.

## Tests

The suite uses mocked HTTP calls and never contacts a real provider:

```bash
python -m pytest
```

Coverage includes storage/migrations, route security, deterministic context, exact final
section order, soundscape combinations, structured/fenced response parsing, provider
authentication/rate-limit/server/network failures, secret redaction, and enhancement
cache boundaries.

## License

Apache-2.0. See [LICENSE](LICENSE).

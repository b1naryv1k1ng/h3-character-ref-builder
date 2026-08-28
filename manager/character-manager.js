const API_PREFIX = "/api/h3-character-ref-builder";
const basePath = window.location.pathname.replace(/\/character-manager\/?$/, "");
const apiUrl = (path) => `${basePath}${API_PREFIX}${path}`;
const fileUrl = (path) => `${basePath}${path}`;
const IMAGE_LIMIT = 9;
const AUDIO_LIMIT = 3;
const IMAGE_ROLES = [
  ["face_identity", "Face / Identity"],
  ["full_body_identity", "Full Body / Physical Identity"],
  ["alternate_identity", "Alternate Identity Angle"],
  ["wardrobe", "Wardrobe / Clothing"],
  ["pose_orientation", "Pose / Orientation"],
  ["expression", "Expression"],
  ["general", "General Reference"],
];
const AUDIO_ROLES = [
  ["voice_identity", "Voice Identity"],
  ["delivery_emotion", "Delivery / Emotion"],
  ["general", "General Audio Reference"],
];

const elements = Object.fromEntries([
  "new-item", "characters-tab", "scenes-tab", "status", "sidebar-title", "item-count",
  "props-tab",
  "item-list", "empty-list", "editor-empty", "empty-title", "empty-message",
  "character-form", "character-title", "character-id", "character-name",
  "character-description", "readiness", "image-library", "audio-library", "image-count",
  "audio-count", "images-empty", "audio-empty", "image-limit-note", "audio-limit-note",
  "add-image", "add-audio", "media-file", "delete-character", "character-dirty",
  "scene-form", "scene-title", "scene-id", "scene-name", "scene-definition", "scene-default-soundscape", "delete-scene",
  "scene-upload-image", "scene-remove-image", "scene-image-file", "scene-reference-preview",
  "scene-reference-image", "scene-reference-empty", "scene-reference-actions",
  "prop-form", "prop-title", "prop-id", "prop-name", "prop-description", "prop-readiness",
  "prop-upload-image", "prop-image-file", "prop-reference-preview", "prop-reference-image",
  "prop-reference-empty", "delete-prop", "prop-dirty",
  "scene-dirty", "confirm-dialog", "confirm-title", "confirm-message",
].map((id) => [id.replaceAll("-", "_"), document.querySelector(`#${id}`)]));

const state = {
  tab: "characters",
  characters: [],
  scenes: [],
  props: [],
  character: null,
  characterOriginal: null,
  scene: null,
  sceneOriginal: null,
  prop: null,
  propOriginal: null,
  dirty: false,
  busy: false,
  fileAction: null,
};
const clone = (value) => JSON.parse(JSON.stringify(value));

async function request(path, options = {}) {
  const response = await fetch(apiUrl(path), { cache: "no-store", ...options });
  let payload;
  try { payload = await response.json(); } catch { throw new Error(`Server returned ${response.status} without JSON.`); }
  if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || `Request failed (${response.status}).`);
  return payload.data;
}

function showStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
  elements.status.hidden = !message;
}

function setDirty(value = true) {
  state.dirty = value;
  elements.character_dirty.hidden = !(value && state.tab === "characters");
  elements.scene_dirty.hidden = !(value && state.tab === "scenes");
  elements.prop_dirty.hidden = !(value && state.tab === "props");
  if (value) showStatus("");
}

function updateControls() {
  const characterSaved = Boolean(state.character?.id);
  const sceneSaved = Boolean(state.scene?.id);
  const propSaved = Boolean(state.prop?.id);
  const imageLimit = (state.character?.images?.length || 0) >= IMAGE_LIMIT;
  const audioLimit = (state.character?.audio?.length || 0) >= AUDIO_LIMIT;
  elements.new_item.disabled = state.busy;
  elements.characters_tab.disabled = state.busy;
  elements.scenes_tab.disabled = state.busy;
  elements.props_tab.disabled = state.busy;
  for (const control of document.querySelectorAll("input, textarea, select, .editor button")) control.disabled = state.busy;
  elements.add_image.disabled = state.busy || !characterSaved || imageLimit;
  elements.add_audio.disabled = state.busy || !characterSaved || audioLimit;
  elements.scene_upload_image.disabled = state.busy || !sceneSaved;
  elements.scene_remove_image.disabled = state.busy || !sceneSaved || !state.scene?.reference_image;
  elements.prop_upload_image.disabled = state.busy || !propSaved;
}

function setBusy(value) { state.busy = value; updateControls(); }

function askConfirm(title, message) {
  elements.confirm_title.textContent = title;
  elements.confirm_message.textContent = message;
  elements.confirm_dialog.showModal();
  return new Promise((resolve) => elements.confirm_dialog.addEventListener(
    "close", () => resolve(elements.confirm_dialog.returnValue === "confirm"), { once: true },
  ));
}

async function mayDiscard() {
  if (!state.dirty) return true;
  return askConfirm("Discard unsaved changes?", "Your unsaved edits will be lost.");
}

function activeCatalog() {
  return state.tab === "characters" ? state.characters : state.tab === "scenes" ? state.scenes : state.props;
}
function activeCurrent() {
  return state.tab === "characters" ? state.character : state.tab === "scenes" ? state.scene : state.prop;
}

function renderList() {
  const catalog = activeCatalog();
  const current = activeCurrent();
  elements.item_list.replaceChildren();
  elements.item_count.textContent = String(catalog.length);
  elements.empty_list.hidden = catalog.length !== 0;
  elements.empty_list.textContent = state.tab === "characters"
    ? "No characters yet. Create one to get started."
    : state.tab === "scenes"
      ? "No Scene Presets yet. Create one to define an environment."
      : "No Prop References yet. Create one to define a reusable visual object.";
  for (const item of catalog) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `character-item${current?.id === item.id ? " active" : ""}`;
    button.textContent = item.name;
    button.title = item.name;
    button.addEventListener("click", () => selectItem(item.id));
    elements.item_list.append(button);
  }
}

function showEmpty() {
  elements.character_form.hidden = true;
  elements.scene_form.hidden = true;
  elements.prop_form.hidden = true;
  elements.editor_empty.hidden = false;
  if (state.tab === "characters") {
    elements.empty_title.textContent = "Select a character";
    elements.empty_message.textContent = "Choose a profile from the list or create a new one.";
  } else if (state.tab === "scenes") {
    elements.empty_title.textContent = "Select a Scene Preset";
    elements.empty_message.textContent = "Choose an environment from the list or create a new one.";
  } else {
    elements.empty_title.textContent = "Select a Prop Reference";
    elements.empty_message.textContent = "Choose a prop from the list or create a new visual reference.";
  }
}

function renderRoleEditor(record, mediaType) {
  const label = document.createElement("label");
  label.className = "reference-role";
  const caption = document.createElement("span");
  caption.textContent = "Role";
  const select = document.createElement("select");
  for (const [value, text] of mediaType === "image" ? IMAGE_ROLES : AUDIO_ROLES) {
    const option = document.createElement("option");
    option.value = value; option.textContent = text; option.selected = record.role === value;
    select.append(option);
  }
  select.addEventListener("change", () => { record.role = select.value; setDirty(); });
  label.append(caption, select);
  return label;
}

function renderLabelEditor(record) {
  const label = document.createElement("label"); label.className = "reference-label";
  const caption = document.createElement("span"); caption.textContent = "Label";
  const input = document.createElement("input"); input.value = record.label; input.maxLength = 200;
  input.addEventListener("input", () => { record.label = input.value; setDirty(); });
  label.append(caption, input); return label;
}

function selectionOption(record, slot, text, checked) {
  const label = document.createElement("label"); label.className = "selection-option";
  const radio = document.createElement("input"); radio.type = "radio"; radio.name = `default-${slot}`;
  radio.checked = checked; radio.addEventListener("change", () => selectDefault(slot, record.id));
  const span = document.createElement("span"); span.textContent = text; label.append(radio, span); return label;
}

function actionButton(text, className, handler) {
  const button = document.createElement("button"); button.type = "button"; button.className = className;
  button.textContent = text; button.addEventListener("click", handler); return button;
}

function renderImage(record) {
  const selected = [state.character.defaults.image_1, state.character.defaults.image_2].includes(record.id);
  const card = document.createElement("article"); card.className = `reference-card${selected ? " selected" : ""}`;
  const preview = document.createElement("div"); preview.className = "reference-preview";
  const image = document.createElement("img"); image.src = `${fileUrl(record.url)}?v=${Date.now()}`;
  image.alt = record.label || "Character image reference"; preview.append(image);
  const metadata = document.createElement("div"); metadata.className = "reference-metadata";
  metadata.append(renderLabelEditor(record), renderRoleEditor(record, "image"));
  const selection = document.createElement("div"); selection.className = "selection-controls";
  selection.append(
    selectionOption(record, "image_1", "Image 1", state.character.defaults.image_1 === record.id),
    selectionOption(record, "image_2", "Image 2", state.character.defaults.image_2 === record.id),
  );
  const actions = document.createElement("div"); actions.className = "reference-actions";
  actions.append(actionButton("Replace", "button secondary compact", () => beginReplace("image", record.id)), actionButton("Delete", "button danger compact", () => deleteReference("image", record)));
  card.append(preview, metadata, selection, actions); return card;
}

function renderAudio(record) {
  const selected = state.character.defaults.audio === record.id;
  const card = document.createElement("article"); card.className = `reference-card audio-card${selected ? " selected" : ""}`;
  const metadata = document.createElement("div"); metadata.className = "reference-metadata";
  metadata.append(renderLabelEditor(record), renderRoleEditor(record, "audio"));
  const player = document.createElement("audio"); player.controls = true; player.src = `${fileUrl(record.url)}?v=${Date.now()}`;
  const side = document.createElement("div"); side.className = "audio-side";
  const selection = document.createElement("div"); selection.className = "selection-controls";
  selection.append(selectionOption(record, "audio", "Active Audio", selected));
  const actions = document.createElement("div"); actions.className = "reference-actions";
  actions.append(actionButton("Replace", "button secondary compact", () => beginReplace("audio", record.id)), actionButton("Delete", "button danger compact", () => deleteReference("audio", record)));
  side.append(selection, actions); card.append(metadata, player, side); return card;
}

function renderLibraries() {
  const images = state.character?.images || []; const audio = state.character?.audio || [];
  elements.image_library.replaceChildren(...images.map(renderImage));
  elements.audio_library.replaceChildren(...audio.map(renderAudio));
  elements.images_empty.hidden = images.length !== 0; elements.audio_empty.hidden = audio.length !== 0;
  elements.image_count.textContent = `${images.length} / ${IMAGE_LIMIT} references`;
  elements.audio_count.textContent = `${audio.length} / ${AUDIO_LIMIT} references`;
  elements.image_limit_note.hidden = images.length < IMAGE_LIMIT; elements.audio_limit_note.hidden = audio.length < AUDIO_LIMIT;
  const missing = [];
  if (!state.character?.id) missing.push("save this character");
  else {
    if (!state.character.defaults.image_1 || !state.character.defaults.image_2) missing.push("select two different active images");
    if (!state.character.defaults.audio) missing.push("select an active audio reference");
  }
  elements.readiness.textContent = missing.length ? `Not generation-ready: ${missing.join(" and ")}.` : "Generation ready: Image 1, Image 2, and Active Audio are selected.";
  elements.readiness.classList.toggle("incomplete", missing.length > 0); updateControls();
}

function renderSceneReference() {
  const reference = state.scene?.reference_image;
  elements.scene_reference_preview.hidden = !reference;
  elements.scene_reference_empty.hidden = Boolean(reference);
  elements.scene_reference_actions.hidden = !reference;
  elements.scene_reference_empty.textContent = state.scene?.id
    ? "No scene reference image. Upload an optional environment reference."
    : "No scene reference image. Save the Scene Preset, then upload an optional environment reference.";
  elements.scene_upload_image.textContent = reference ? "Replace" : "Upload";
  if (reference) {
    elements.scene_reference_image.src = `${fileUrl(reference.url)}?v=${Date.now()}`;
  } else {
    elements.scene_reference_image.removeAttribute("src");
  }
  updateControls();
}

function renderPropReference() {
  const reference = state.prop?.reference_image;
  elements.prop_reference_preview.hidden = !reference;
  elements.prop_reference_empty.hidden = Boolean(reference);
  elements.prop_upload_image.textContent = reference ? "Replace" : "Upload";
  elements.prop_readiness.textContent = reference
    ? "Usable: this Prop Reference can be selected in H3 Character Reference."
    : "Not usable yet: upload the required reference image.";
  elements.prop_readiness.classList.toggle("incomplete", !reference);
  if (reference) elements.prop_reference_image.src = `${fileUrl(reference.url)}?v=${Date.now()}`;
  else elements.prop_reference_image.removeAttribute("src");
  updateControls();
}

function showProp(prop) {
  state.prop = clone(prop); state.propOriginal = clone(prop);
  state.character = null; state.characterOriginal = null; state.scene = null; state.sceneOriginal = null;
  elements.editor_empty.hidden = true; elements.character_form.hidden = true; elements.scene_form.hidden = true; elements.prop_form.hidden = false;
  elements.prop_name.value = prop.name || ""; elements.prop_description.value = prop.description || "";
  elements.prop_title.textContent = prop.id ? prop.name : "New Prop Reference";
  elements.prop_id.textContent = prop.id ? `UUID ${prop.id}` : "UUID assigned on save";
  elements.delete_prop.hidden = !prop.id; setDirty(false); renderList(); renderPropReference(); elements.prop_name.focus();
}

function showCharacter(profile) {
  state.character = clone(profile); state.characterOriginal = clone(profile); state.scene = null; state.sceneOriginal = null;
  state.prop = null; state.propOriginal = null;
  elements.editor_empty.hidden = true; elements.scene_form.hidden = true; elements.prop_form.hidden = true; elements.character_form.hidden = false;
  elements.character_name.value = profile.name || ""; elements.character_description.value = profile.description || "";
  elements.character_title.textContent = profile.id ? profile.name : "New Character";
  elements.character_id.textContent = profile.id ? `UUID ${profile.id}` : "UUID assigned on save";
  elements.delete_character.hidden = !profile.id; setDirty(false); renderLibraries(); renderList(); elements.character_name.focus();
}

function showScene(scene) {
  state.scene = clone(scene); state.sceneOriginal = clone(scene); state.character = null; state.characterOriginal = null;
  state.prop = null; state.propOriginal = null;
  elements.editor_empty.hidden = true; elements.character_form.hidden = true; elements.prop_form.hidden = true; elements.scene_form.hidden = false;
  elements.scene_name.value = scene.name || ""; elements.scene_definition.value = scene.definition || ""; elements.scene_default_soundscape.value = scene.default_soundscape || "";
  elements.scene_title.textContent = scene.id ? scene.name : "New Scene Preset";
  elements.scene_id.textContent = scene.id ? `UUID ${scene.id}` : "UUID assigned on save";
  elements.delete_scene.hidden = !scene.id; setDirty(false); renderList(); renderSceneReference(); elements.scene_name.focus();
}

async function refreshCatalogs() {
  [state.characters, state.scenes, state.props] = await Promise.all([request("/characters"), request("/scenes"), request("/props")]);
  renderList();
}

async function selectItem(id) {
  if (state.busy || activeCurrent()?.id === id || !(await mayDiscard())) return;
  try {
    showStatus("");
    if (state.tab === "characters") showCharacter(await request(`/characters/${encodeURIComponent(id)}`));
    else if (state.tab === "scenes") showScene(await request(`/scenes/${encodeURIComponent(id)}`));
    else showProp(await request(`/props/${encodeURIComponent(id)}`));
  } catch (error) { showStatus(error.message, "error"); await refreshCatalogs(); }
}

async function switchTab(tab) {
  if (state.tab === tab || state.busy || !(await mayDiscard())) return;
  state.tab = tab; state.character = null; state.scene = null; state.prop = null; setDirty(false); showStatus("");
  const characters = tab === "characters";
  const scenes = tab === "scenes";
  elements.characters_tab.classList.toggle("active", characters); elements.scenes_tab.classList.toggle("active", scenes); elements.props_tab.classList.toggle("active", tab === "props");
  elements.characters_tab.setAttribute("aria-selected", String(characters)); elements.scenes_tab.setAttribute("aria-selected", String(scenes)); elements.props_tab.setAttribute("aria-selected", String(tab === "props"));
  elements.sidebar_title.textContent = characters ? "Characters" : scenes ? "Scene Presets" : "Prop References";
  elements.new_item.textContent = characters ? "+ New Character" : scenes ? "+ New Scene Preset" : "+ New Prop Reference";
  showEmpty(); renderList();
  const first = activeCatalog()[0]; if (first) await selectItem(first.id);
}

async function newItem() {
  if (state.busy || !(await mayDiscard())) return; showStatus("");
  if (state.tab === "characters") showCharacter({ schema_version: 3, id: null, name: "", description: "", images: [], audio: [], defaults: { image_1: null, image_2: null, audio: null }, generation_ready: false });
  else if (state.tab === "scenes") showScene({ schema_version: 3, id: null, name: "", definition: "", default_soundscape: "", reference_image: null });
  else showProp({ schema_version: 1, id: null, name: "", description: "", reference_image: null, usable: false });
}

function validateUniqueName(value, catalog, currentId, label) {
  const name = value.trim(); if (!name) throw new Error(`${label} name is required.`);
  if (catalog.some((item) => item.id !== currentId && item.name.toLocaleLowerCase() === name.toLocaleLowerCase())) throw new Error(`A ${label.toLowerCase()} named "${name}" already exists.`);
  return name;
}

async function persistCharacter() {
  const name = validateUniqueName(elements.character_name.value, state.characters, state.character?.id, "Character");
  const body = JSON.stringify({ name, description: elements.character_description.value });
  let profile;
  if (!state.character.id) profile = await request("/characters", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  else {
    profile = await request(`/characters/${encodeURIComponent(state.character.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body });
    const originals = new Map([...state.characterOriginal.images, ...state.characterOriginal.audio].map((item) => [item.id, item]));
    for (const record of [...state.character.images, ...state.character.audio]) {
      const original = originals.get(record.id); const changed = {};
      if (original?.label !== record.label) changed.label = record.label;
      if (original?.role !== record.role) changed.role = record.role;
      if (Object.keys(changed).length) profile = await request(`/characters/${encodeURIComponent(state.character.id)}/media/${encodeURIComponent(record.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changed) });
    }
    profile = await request(`/characters/${encodeURIComponent(state.character.id)}/defaults`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.character.defaults) });
  }
  showCharacter(profile); await refreshCatalogs(); return profile;
}

async function saveCharacter(event) {
  event.preventDefault(); if (state.busy) return;
  try { setBusy(true); showStatus("Saving character…"); const profile = await persistCharacter(); showStatus(`Saved ${profile.name}.${profile.generation_ready ? " The profile is generation-ready." : " Select the missing active references."}`, "success"); }
  catch (error) { showStatus(error.message, "error"); } finally { setBusy(false); }
}

async function persistScene() {
  const name = validateUniqueName(elements.scene_name.value, state.scenes, state.scene?.id, "Scene Preset");
  const body = JSON.stringify({ name, definition: elements.scene_definition.value, default_soundscape: elements.scene_default_soundscape.value });
  const scene = await request(state.scene.id ? `/scenes/${encodeURIComponent(state.scene.id)}` : "/scenes", { method: state.scene.id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body });
  showScene(scene); await refreshCatalogs(); return scene;
}

async function saveScene(event) {
  event.preventDefault(); if (state.busy) return;
  try {
    setBusy(true); showStatus("Saving Scene Preset…");
    const scene = await persistScene(); showStatus(`Saved ${scene.name}.`, "success");
  } catch (error) { showStatus(error.message, "error"); } finally { setBusy(false); }
}

async function savePendingScene() { if (state.dirty) await persistScene(); }

function beginSceneImageUpload() {
  if (!state.scene?.id || state.busy) return;
  elements.scene_image_file.value = "";
  elements.scene_image_file.click();
}

async function handleSceneImageFile(file) {
  if (!file || !state.scene?.id || state.busy) return;
  const replacing = Boolean(state.scene.reference_image);
  try {
    setBusy(true); await savePendingScene();
    const form = new FormData(); form.append("file", file, file.name);
    const scene = await request(`/scenes/${encodeURIComponent(state.scene.id)}/reference-image`, { method: "POST", body: form });
    showScene(scene); await refreshCatalogs();
    showStatus(replacing ? "Scene reference image replaced." : "Scene reference image uploaded.", "success");
  } catch (error) { showStatus(error.message, "error"); }
  finally { elements.scene_image_file.value = ""; setBusy(false); }
}

async function removeSceneImage() {
  if (!state.scene?.reference_image || state.busy) return;
  if (!(await askConfirm("Remove scene reference image?", "This permanently removes the managed image. The Scene Preset will remain available as text-only."))) return;
  try {
    setBusy(true); await savePendingScene();
    const scene = await request(`/scenes/${encodeURIComponent(state.scene.id)}/reference-image`, { method: "DELETE" });
    showScene(scene); await refreshCatalogs(); showStatus("Scene reference image removed.", "success");
  } catch (error) { showStatus(error.message, "error"); } finally { setBusy(false); }
}

async function persistProp() {
  const name = validateUniqueName(elements.prop_name.value, state.props, state.prop?.id, "Prop Reference");
  const body = JSON.stringify({ name, description: elements.prop_description.value });
  const prop = await request(state.prop.id ? `/props/${encodeURIComponent(state.prop.id)}` : "/props", { method: state.prop.id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body });
  showProp(prop); await refreshCatalogs(); return prop;
}

async function saveProp(event) {
  event.preventDefault(); if (state.busy) return;
  try {
    setBusy(true); showStatus("Saving Prop Reference…");
    const prop = await persistProp();
    showStatus(prop.reference_image ? `Saved ${prop.name}.` : `Saved ${prop.name}. Upload its required image before using it in a node.`, "success");
  } catch (error) { showStatus(error.message, "error"); } finally { setBusy(false); }
}

async function savePendingProp() { if (state.dirty) await persistProp(); }

function beginPropImageUpload() {
  if (!state.prop?.id || state.busy) return;
  elements.prop_image_file.value = "";
  elements.prop_image_file.click();
}

async function handlePropImageFile(file) {
  if (!file || !state.prop?.id || state.busy) return;
  const replacing = Boolean(state.prop.reference_image);
  try {
    setBusy(true); await savePendingProp();
    const form = new FormData(); form.append("file", file, file.name);
    const prop = await request(`/props/${encodeURIComponent(state.prop.id)}/reference-image`, { method: "POST", body: form });
    showProp(prop); await refreshCatalogs();
    showStatus(replacing ? "Prop reference image replaced." : "Prop reference image uploaded. This prop is now usable.", "success");
  } catch (error) { showStatus(error.message, "error"); }
  finally { elements.prop_image_file.value = ""; setBusy(false); }
}

function selectDefault(slot, mediaId) {
  if (slot !== "audio") { const other = slot === "image_1" ? "image_2" : "image_1"; if (state.character.defaults[other] === mediaId) { showStatus("Image 1 and Image 2 must use different references.", "error"); renderLibraries(); return; } }
  state.character.defaults[slot] = mediaId; setDirty(); renderLibraries();
}

async function savePendingCharacter() { if (state.dirty) await persistCharacter(); }
function beginAdd(mediaType) {
  if (!state.character?.id || state.busy) return;
  const collection = mediaType === "image" ? state.character.images : state.character.audio; const limit = mediaType === "image" ? IMAGE_LIMIT : AUDIO_LIMIT;
  if (collection.length >= limit) return showStatus(`The ${limit}-${mediaType} reference limit has been reached.`, "error");
  state.fileAction = { kind: "add", mediaType }; elements.media_file.accept = mediaType === "image" ? "image/png,image/jpeg,image/webp" : "audio/wav,audio/mpeg,audio/flac,audio/mp4,audio/ogg,audio/aac,.m4a"; elements.media_file.value = ""; elements.media_file.click();
}
function beginReplace(mediaType, mediaId) { if (!state.busy) { state.fileAction = { kind: "replace", mediaType, mediaId }; elements.media_file.accept = mediaType === "image" ? "image/png,image/jpeg,image/webp" : "audio/*,.m4a"; elements.media_file.value = ""; elements.media_file.click(); } }
function defaultLabel(filename) { return filename.replace(/\.[^.]+$/, "").replaceAll("_", " ").trim(); }

async function handleMediaFile(file) {
  const action = state.fileAction; if (!file || !action || state.busy) return;
  try {
    setBusy(true); await savePendingCharacter(); const form = new FormData(); form.append("file", file, file.name);
    let path;
    if (action.kind === "add") { form.append("type", action.mediaType); form.append("label", defaultLabel(file.name)); form.append("role", "general"); path = `/characters/${encodeURIComponent(state.character.id)}/media`; }
    else path = `/characters/${encodeURIComponent(state.character.id)}/media/${encodeURIComponent(action.mediaId)}`;
    const profile = await request(path, { method: action.kind === "add" ? "POST" : "PUT", body: form }); showCharacter(profile);
    showStatus(action.kind === "add" ? "Reference added. Set its role and active slot, then save." : "Reference file replaced; its media UUID and role were preserved.", "success");
  } catch (error) { showStatus(error.message, "error"); } finally { state.fileAction = null; elements.media_file.value = ""; setBusy(false); }
}

function configureDropTarget(section, mediaType) {
  for (const eventName of ["dragenter", "dragover"]) {
    section.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (state.character?.id && !state.busy) section.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    section.addEventListener(eventName, (event) => {
      event.preventDefault();
      section.classList.remove("dragging");
    });
  }
  section.addEventListener("drop", (event) => {
    if (!state.character?.id || state.busy) {
      showStatus("Save this character before adding references.", "error");
      return;
    }
    const collection = mediaType === "image" ? state.character.images : state.character.audio;
    const limit = mediaType === "image" ? IMAGE_LIMIT : AUDIO_LIMIT;
    if (collection.length >= limit) {
      showStatus(`The ${limit}-${mediaType} reference limit has been reached.`, "error");
      return;
    }
    const file = event.dataTransfer.files[0];
    if (file) {
      state.fileAction = { kind: "add", mediaType };
      void handleMediaFile(file);
    }
  });
}

async function deleteReference(mediaType, record) {
  if (state.busy) return; const selected = Object.values(state.character.defaults).includes(record.id);
  if (!(await askConfirm(`Delete ${record.label || `${mediaType} reference`}?`, selected ? "This active reference will be removed and its default cleared." : "This permanently removes the managed media file."))) return;
  try { setBusy(true); await savePendingCharacter(); const profile = await request(`/characters/${encodeURIComponent(state.character.id)}/media/${encodeURIComponent(record.id)}`, { method: "DELETE" }); showCharacter(profile); showStatus("Reference deleted.", "success"); }
  catch (error) { showStatus(error.message, "error"); } finally { setBusy(false); }
}

async function deleteCurrent() {
  const current = activeCurrent(); if (!current?.id || state.busy) return;
  const label = state.tab === "characters" ? "character and all managed references" : state.tab === "scenes" ? "Scene Preset" : "Prop Reference and its managed image";
  const collection = state.tab === "characters" ? "characters" : state.tab === "scenes" ? "scenes" : "props";
  const display = state.tab === "characters" ? "Character" : state.tab === "scenes" ? "Scene Preset" : "Prop Reference";
  if (!(await askConfirm(`Delete ${current.name}?`, `This permanently removes this ${label}. Saved workflows using its UUID will report that it no longer exists.`))) return;
  try { setBusy(true); await request(`/${collection}/${encodeURIComponent(current.id)}`, { method: "DELETE" }); state.character = null; state.scene = null; state.prop = null; setDirty(false); await refreshCatalogs(); showEmpty(); const first = activeCatalog()[0]; if (first) await selectItem(first.id); showStatus(`${display} deleted.`, "success"); }
  catch (error) { showStatus(error.message, "error"); } finally { setBusy(false); }
}

for (const input of [elements.character_name, elements.character_description]) input.addEventListener("input", () => {
  if (state.character) { state.character.name = elements.character_name.value; state.character.description = elements.character_description.value; elements.character_title.textContent = elements.character_name.value.trim() || "New Character"; setDirty(); }
});
for (const input of [elements.scene_name, elements.scene_definition, elements.scene_default_soundscape]) input.addEventListener("input", () => {
  if (state.scene) { state.scene.name = elements.scene_name.value; state.scene.definition = elements.scene_definition.value; state.scene.default_soundscape = elements.scene_default_soundscape.value; elements.scene_title.textContent = elements.scene_name.value.trim() || "New Scene Preset"; setDirty(); }
});
for (const input of [elements.prop_name, elements.prop_description]) input.addEventListener("input", () => {
  if (state.prop) { state.prop.name = elements.prop_name.value; state.prop.description = elements.prop_description.value; elements.prop_title.textContent = elements.prop_name.value.trim() || "New Prop Reference"; setDirty(); }
});
elements.characters_tab.addEventListener("click", () => switchTab("characters")); elements.scenes_tab.addEventListener("click", () => switchTab("scenes")); elements.props_tab.addEventListener("click", () => switchTab("props"));
elements.new_item.addEventListener("click", newItem); elements.character_form.addEventListener("submit", saveCharacter); elements.scene_form.addEventListener("submit", saveScene); elements.prop_form.addEventListener("submit", saveProp);
elements.delete_character.addEventListener("click", deleteCurrent); elements.delete_scene.addEventListener("click", deleteCurrent); elements.delete_prop.addEventListener("click", deleteCurrent);
elements.add_image.addEventListener("click", () => beginAdd("image")); elements.add_audio.addEventListener("click", () => beginAdd("audio")); elements.media_file.addEventListener("change", () => handleMediaFile(elements.media_file.files[0]));
elements.scene_upload_image.addEventListener("click", beginSceneImageUpload);
elements.scene_remove_image.addEventListener("click", removeSceneImage);
elements.scene_image_file.addEventListener("change", () => handleSceneImageFile(elements.scene_image_file.files[0]));
elements.prop_upload_image.addEventListener("click", beginPropImageUpload);
elements.prop_image_file.addEventListener("change", () => handlePropImageFile(elements.prop_image_file.files[0]));
configureDropTarget(elements.image_library.closest(".library-section"), "image");
configureDropTarget(elements.audio_library.closest(".library-section"), "audio");
window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("focus", () => { if (!state.dirty && !state.busy) refreshCatalogs().catch((error) => showStatus(error.message, "error")); });

refreshCatalogs().then(async () => { const first = state.characters[0]; if (first) await selectItem(first.id); else showEmpty(); }).catch((error) => showStatus(error.message, "error"));

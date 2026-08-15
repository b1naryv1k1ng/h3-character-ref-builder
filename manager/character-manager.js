const API_PREFIX = "/api/h3-character-ref-builder";
const pageSuffix = /\/character-manager\/?$/;
const basePath = window.location.pathname.replace(pageSuffix, "");
const apiUrl = (path) => `${basePath}${API_PREFIX}${path}`;
const fileUrl = (path) => `${basePath}${path}`;
const IMAGE_LIMIT = 9;
const AUDIO_LIMIT = 3;

const elements = {
  list: document.querySelector("#character-list"),
  emptyList: document.querySelector("#empty-list"),
  count: document.querySelector("#character-count"),
  emptyEditor: document.querySelector("#editor-empty"),
  form: document.querySelector("#editor-form"),
  title: document.querySelector("#editor-title"),
  id: document.querySelector("#character-id"),
  name: document.querySelector("#name"),
  description: document.querySelector("#description"),
  readiness: document.querySelector("#readiness"),
  imageLibrary: document.querySelector("#image-library"),
  audioLibrary: document.querySelector("#audio-library"),
  imageCount: document.querySelector("#image-count"),
  audioCount: document.querySelector("#audio-count"),
  imagesEmpty: document.querySelector("#images-empty"),
  audioEmpty: document.querySelector("#audio-empty"),
  imageLimitNote: document.querySelector("#image-limit-note"),
  audioLimitNote: document.querySelector("#audio-limit-note"),
  addImage: document.querySelector("#add-image"),
  addAudio: document.querySelector("#add-audio"),
  mediaFile: document.querySelector("#media-file"),
  newButton: document.querySelector("#new-character"),
  deleteButton: document.querySelector("#delete-character"),
  saveButton: document.querySelector("#save-character"),
  dirtyNote: document.querySelector("#dirty-note"),
  status: document.querySelector("#status"),
  dialog: document.querySelector("#confirm-dialog"),
  dialogTitle: document.querySelector("#confirm-title"),
  dialogMessage: document.querySelector("#confirm-message"),
};

const state = {
  profiles: [],
  current: null,
  original: null,
  dirty: false,
  busy: false,
  fileAction: null,
};

const clone = (value) => JSON.parse(JSON.stringify(value));

async function request(path, options = {}) {
  const response = await fetch(apiUrl(path), { cache: "no-store", ...options });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Server returned ${response.status} without a JSON response.`);
  }
  if (!response.ok || !payload.ok) {
    throw new Error(payload?.error?.message || `Request failed (${response.status}).`);
  }
  return payload.data;
}

function showStatus(message, type = "") {
  elements.status.textContent = message;
  elements.status.className = `status ${type}`.trim();
  elements.status.hidden = !message;
}

function updateControlStates() {
  const saved = Boolean(state.current?.id);
  const imageLimit = (state.current?.images?.length || 0) >= IMAGE_LIMIT;
  const audioLimit = (state.current?.audio?.length || 0) >= AUDIO_LIMIT;
  elements.newButton.disabled = state.busy;
  elements.saveButton.disabled = state.busy;
  elements.deleteButton.disabled = state.busy;
  elements.name.disabled = state.busy;
  elements.description.disabled = state.busy;
  elements.addImage.disabled = state.busy || !saved || imageLimit;
  elements.addAudio.disabled = state.busy || !saved || audioLimit;
  for (const control of elements.form.querySelectorAll(".reference-card button, .reference-card input")) {
    control.disabled = state.busy;
  }
}

function setBusy(busy) {
  state.busy = busy;
  updateControlStates();
}

function setDirty(dirty = true) {
  state.dirty = dirty;
  elements.dirtyNote.hidden = !dirty;
}

function askConfirm(title, message) {
  elements.dialogTitle.textContent = title;
  elements.dialogMessage.textContent = message;
  elements.dialog.showModal();
  return new Promise((resolve) => {
    elements.dialog.addEventListener(
      "close",
      () => resolve(elements.dialog.returnValue === "confirm"),
      { once: true },
    );
  });
}

async function mayDiscardChanges() {
  if (!state.dirty) return true;
  return askConfirm(
    "Discard unsaved changes?",
    "Name, description, labels, and active-reference selections will be lost.",
  );
}

function renderList() {
  elements.list.replaceChildren();
  elements.count.textContent = String(state.profiles.length);
  elements.emptyList.hidden = state.profiles.length !== 0;
  for (const profile of state.profiles) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `character-item${state.current?.id === profile.id ? " active" : ""}`;
    button.textContent = profile.name;
    button.title = profile.name;
    button.addEventListener("click", () => selectCharacter(profile.id));
    elements.list.append(button);
  }
}

function readinessDetails() {
  if (!state.current?.id) {
    return { ready: false, message: "Save this character before adding references." };
  }
  const missing = [];
  if (!state.current.defaults.image_1 || !state.current.defaults.image_2) {
    missing.push("select two different active images");
  }
  if (!state.current.defaults.audio) missing.push("select an active audio reference");
  if (!missing.length) {
    return {
      ready: true,
      message: "Generation ready: Image 1, Image 2, and Active Audio are selected.",
    };
  }
  return { ready: false, message: `Not generation-ready: ${missing.join(" and ")}.` };
}

function renderReadiness() {
  const readiness = readinessDetails();
  elements.readiness.textContent = readiness.message;
  elements.readiness.classList.toggle("incomplete", !readiness.ready);
}

function createButton(label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function createLabelEditor(record) {
  const label = document.createElement("label");
  label.className = "reference-label";
  const caption = document.createElement("span");
  caption.textContent = "Reference label";
  const input = document.createElement("input");
  input.value = record.label;
  input.maxLength = 200;
  input.placeholder = "Describe this reference";
  input.addEventListener("input", () => {
    record.label = input.value;
    setDirty();
  });
  label.append(caption, input);
  return label;
}

function createSelectionOption(record, slot, labelText, checked) {
  const label = document.createElement("label");
  label.className = "selection-option";
  const radio = document.createElement("input");
  radio.type = "radio";
  radio.name = `default-${slot}`;
  radio.value = record.id;
  radio.checked = checked;
  radio.addEventListener("change", () => selectDefault(slot, record.id));
  const text = document.createElement("span");
  text.textContent = labelText;
  label.append(radio, text);
  return label;
}

function renderImageCard(record) {
  const selected = [state.current.defaults.image_1, state.current.defaults.image_2].includes(record.id);
  const card = document.createElement("article");
  card.className = `reference-card${selected ? " selected" : ""}`;
  card.dataset.mediaId = record.id;

  const preview = document.createElement("div");
  preview.className = "reference-preview";
  const image = document.createElement("img");
  image.src = `${fileUrl(record.url)}?v=${Date.now()}`;
  image.alt = record.label || "Character image reference";
  preview.append(image);

  const controls = document.createElement("div");
  controls.className = "selection-controls";
  controls.append(
    createSelectionOption(record, "image_1", "Image 1", state.current.defaults.image_1 === record.id),
    createSelectionOption(record, "image_2", "Image 2", state.current.defaults.image_2 === record.id),
  );

  const actions = document.createElement("div");
  actions.className = "reference-actions";
  actions.append(
    createButton("Replace", "button secondary compact", () => beginReplace("image", record.id)),
    createButton("Delete", "button danger compact", () => deleteReference("image", record)),
  );
  card.append(preview, createLabelEditor(record), controls, actions);
  return card;
}

function renderAudioCard(record) {
  const selected = state.current.defaults.audio === record.id;
  const card = document.createElement("article");
  card.className = `reference-card audio-card${selected ? " selected" : ""}`;
  card.dataset.mediaId = record.id;

  const player = document.createElement("audio");
  player.controls = true;
  player.src = `${fileUrl(record.url)}?v=${Date.now()}`;

  const side = document.createElement("div");
  side.className = "audio-side";
  const controls = document.createElement("div");
  controls.className = "selection-controls";
  controls.append(
    createSelectionOption(record, "audio", "Active Audio", selected),
  );
  const actions = document.createElement("div");
  actions.className = "reference-actions";
  actions.append(
    createButton("Replace", "button secondary compact", () => beginReplace("audio", record.id)),
    createButton("Delete", "button danger compact", () => deleteReference("audio", record)),
  );
  side.append(controls, actions);
  card.append(createLabelEditor(record), player, side);
  return card;
}

function renderLibraries() {
  elements.imageLibrary.replaceChildren();
  elements.audioLibrary.replaceChildren();
  const images = state.current?.images || [];
  const audio = state.current?.audio || [];
  for (const record of images) elements.imageLibrary.append(renderImageCard(record));
  for (const record of audio) elements.audioLibrary.append(renderAudioCard(record));
  elements.imagesEmpty.hidden = images.length !== 0;
  elements.audioEmpty.hidden = audio.length !== 0;
  elements.imageCount.textContent = `${images.length} / ${IMAGE_LIMIT} references`;
  elements.audioCount.textContent = `${audio.length} / ${AUDIO_LIMIT} references`;
  elements.imageLimitNote.hidden = images.length < IMAGE_LIMIT;
  elements.audioLimitNote.hidden = audio.length < AUDIO_LIMIT;
  renderReadiness();
  updateControlStates();
}

function showEditor(profile) {
  state.current = clone(profile);
  state.original = clone(profile);
  elements.emptyEditor.hidden = true;
  elements.form.hidden = false;
  elements.name.value = profile.name || "";
  elements.description.value = profile.description || "";
  elements.title.textContent = profile.id ? profile.name : "New Character";
  elements.id.textContent = profile.id ? `UUID ${profile.id}` : "UUID assigned on save";
  elements.deleteButton.hidden = !profile.id;
  setDirty(false);
  renderLibraries();
  renderList();
  elements.name.focus();
}

function selectDefault(slot, mediaId) {
  if (slot === "image_1" || slot === "image_2") {
    const otherSlot = slot === "image_1" ? "image_2" : "image_1";
    if (state.current.defaults[otherSlot] === mediaId) {
      showStatus("Image 1 and Image 2 must use different references.", "error");
      renderLibraries();
      return;
    }
  }
  state.current.defaults[slot] = mediaId;
  showStatus("");
  setDirty();
  renderLibraries();
}

async function selectCharacter(id) {
  if (state.busy || state.current?.id === id) return;
  if (!(await mayDiscardChanges())) return;
  try {
    showStatus("");
    showEditor(await request(`/characters/${encodeURIComponent(id)}`));
  } catch (error) {
    showStatus(error.message, "error");
    await refreshProfiles();
  }
}

async function refreshProfiles() {
  state.profiles = await request("/characters");
  renderList();
}

async function loadInitial() {
  await refreshProfiles();
  if (state.profiles.length) {
    showEditor(await request(`/characters/${encodeURIComponent(state.profiles[0].id)}`));
  }
}

async function newCharacter() {
  if (state.busy || !(await mayDiscardChanges())) return;
  showStatus("");
  showEditor({
    schema_version: 2,
    id: null,
    name: "",
    description: "",
    images: [],
    audio: [],
    defaults: { image_1: null, image_2: null, audio: null },
    generation_ready: false,
  });
}

function validateName() {
  const name = elements.name.value.trim();
  if (!name) throw new Error("Character name is required.");
  const duplicate = state.profiles.find(
    (profile) => profile.id !== state.current?.id && profile.name.toLocaleLowerCase() === name.toLocaleLowerCase(),
  );
  if (duplicate) throw new Error(`A character named "${name}" already exists.`);
  return name;
}

async function persistEdits() {
  const name = validateName();
  const metadataBody = JSON.stringify({ name, description: elements.description.value });
  let profile;
  if (!state.current.id) {
    profile = await request("/characters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: metadataBody,
    });
  } else {
    profile = await request(`/characters/${encodeURIComponent(state.current.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: metadataBody,
    });
    const originalLabels = new Map(
      [...state.original.images, ...state.original.audio].map((record) => [record.id, record.label]),
    );
    for (const record of [...state.current.images, ...state.current.audio]) {
      if (originalLabels.get(record.id) !== record.label) {
        profile = await request(
          `/characters/${encodeURIComponent(state.current.id)}/media/${encodeURIComponent(record.id)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: record.label }),
          },
        );
      }
    }
    profile = await request(`/characters/${encodeURIComponent(state.current.id)}/defaults`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.current.defaults),
    });
  }
  showEditor(profile);
  await refreshProfiles();
  return profile;
}

async function saveCharacter(event) {
  event.preventDefault();
  if (state.busy) return;
  try {
    setBusy(true);
    showStatus("Saving character…");
    const profile = await persistEdits();
    showStatus(
      profile.generation_ready
        ? `Saved ${profile.name}. The profile is generation-ready.`
        : `Saved ${profile.name}. Add or select the missing active references.`,
      "success",
    );
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function savePendingEdits() {
  if (!state.dirty) return;
  showStatus("Saving pending edits before modifying media…");
  await persistEdits();
}

function beginAdd(mediaType) {
  if (!state.current?.id || state.busy) return;
  const collection = mediaType === "image" ? state.current.images : state.current.audio;
  const limit = mediaType === "image" ? IMAGE_LIMIT : AUDIO_LIMIT;
  if (collection.length >= limit) {
    showStatus(`The ${limit}-${mediaType} reference limit has been reached.`, "error");
    return;
  }
  state.fileAction = { kind: "add", mediaType };
  elements.mediaFile.accept = mediaType === "image"
    ? "image/png,image/jpeg,image/webp"
    : "audio/wav,audio/mpeg,audio/flac,audio/mp4,audio/ogg,audio/aac,.m4a";
  elements.mediaFile.value = "";
  elements.mediaFile.click();
}

function beginReplace(mediaType, mediaId) {
  if (state.busy) return;
  state.fileAction = { kind: "replace", mediaType, mediaId };
  elements.mediaFile.accept = mediaType === "image"
    ? "image/png,image/jpeg,image/webp"
    : "audio/wav,audio/mpeg,audio/flac,audio/mp4,audio/ogg,audio/aac,.m4a";
  elements.mediaFile.value = "";
  elements.mediaFile.click();
}

function defaultLabel(filename) {
  return filename.replace(/\.[^.]+$/, "").replaceAll("_", " ").trim();
}

function validateChosenFile(mediaType, file) {
  const validImage = ["image/png", "image/jpeg", "image/webp"].includes(file.type)
    || /\.(png|jpe?g|webp)$/i.test(file.name);
  const validAudio = file.type.startsWith("audio/")
    || /\.(wav|mp3|flac|m4a|ogg|aac)$/i.test(file.name);
  if (mediaType === "image" && !validImage) throw new Error("Images must be PNG, JPEG, or WebP.");
  if (mediaType === "audio" && !validAudio) throw new Error("Audio must be WAV, MP3, FLAC, M4A, OGG, or AAC.");
}

async function handleMediaFile(file, action = state.fileAction) {
  if (!file || !action || state.busy) return;
  try {
    validateChosenFile(action.mediaType, file);
    setBusy(true);
    await savePendingEdits();
    const form = new FormData();
    form.append("file", file, file.name);
    let path;
    let method;
    if (action.kind === "add") {
      form.append("type", action.mediaType);
      form.append("label", defaultLabel(file.name));
      path = `/characters/${encodeURIComponent(state.current.id)}/media`;
      method = "POST";
    } else {
      path = `/characters/${encodeURIComponent(state.current.id)}/media/${encodeURIComponent(action.mediaId)}`;
      method = "PUT";
    }
    showStatus(action.kind === "add" ? "Adding reference…" : "Replacing reference…");
    const profile = await request(path, { method, body: form });
    showEditor(profile);
    showStatus(
      action.kind === "add"
        ? "Reference added. Choose its active slot and save."
        : "Reference file replaced; its media UUID was preserved.",
      "success",
    );
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    state.fileAction = null;
    elements.mediaFile.value = "";
    setBusy(false);
  }
}

async function deleteReference(mediaType, record) {
  if (state.busy) return;
  const selected = Object.values(state.current.defaults).includes(record.id);
  const confirmed = await askConfirm(
    `Delete ${record.label || `${mediaType} reference`}?`,
    selected
      ? "This reference is active. Deleting it will clear its default selection and make the character incomplete until another reference is selected."
      : "This permanently removes the managed media file from this character.",
  );
  if (!confirmed) return;
  try {
    setBusy(true);
    await savePendingEdits();
    const profile = await request(
      `/characters/${encodeURIComponent(state.current.id)}/media/${encodeURIComponent(record.id)}`,
      { method: "DELETE" },
    );
    showEditor(profile);
    showStatus("Reference deleted.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function deleteCharacter() {
  if (!state.current?.id || state.busy) return;
  const confirmed = await askConfirm(
    `Delete ${state.current.name}?`,
    "This permanently removes the profile and every managed image and audio reference. Saved workflows using its UUID will report that the profile no longer exists.",
  );
  if (!confirmed) return;
  try {
    setBusy(true);
    await request(`/characters/${encodeURIComponent(state.current.id)}`, { method: "DELETE" });
    state.current = null;
    state.original = null;
    setDirty(false);
    elements.form.hidden = true;
    elements.emptyEditor.hidden = false;
    await refreshProfiles();
    if (state.profiles.length) {
      showEditor(await request(`/characters/${encodeURIComponent(state.profiles[0].id)}`));
    }
    showStatus("Character deleted.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function configureDropTarget(section, mediaType) {
  for (const eventName of ["dragenter", "dragover"]) {
    section.addEventListener(eventName, (event) => {
      event.preventDefault();
      if (state.current?.id && !state.busy) section.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    section.addEventListener(eventName, (event) => {
      event.preventDefault();
      section.classList.remove("dragging");
    });
  }
  section.addEventListener("drop", (event) => {
    if (!state.current?.id || state.busy) {
      showStatus("Save this character before adding references.", "error");
      return;
    }
    const collection = mediaType === "image" ? state.current.images : state.current.audio;
    const limit = mediaType === "image" ? IMAGE_LIMIT : AUDIO_LIMIT;
    if (collection.length >= limit) {
      showStatus(`The ${limit}-${mediaType} reference limit has been reached.`, "error");
      return;
    }
    const file = event.dataTransfer.files[0];
    if (file) void handleMediaFile(file, { kind: "add", mediaType });
  });
}

for (const input of [elements.name, elements.description]) {
  input.addEventListener("input", () => {
    if (input === elements.name) elements.title.textContent = input.value.trim() || "New Character";
    if (state.current) {
      state.current.name = elements.name.value;
      state.current.description = elements.description.value;
    }
    setDirty();
  });
}

elements.newButton.addEventListener("click", newCharacter);
elements.form.addEventListener("submit", saveCharacter);
elements.deleteButton.addEventListener("click", deleteCharacter);
elements.addImage.addEventListener("click", () => beginAdd("image"));
elements.addAudio.addEventListener("click", () => beginAdd("audio"));
elements.mediaFile.addEventListener("change", () => handleMediaFile(elements.mediaFile.files[0]));
configureDropTarget(elements.imageLibrary.closest(".library-section"), "image");
configureDropTarget(elements.audioLibrary.closest(".library-section"), "audio");

window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

loadInitial().catch((error) => showStatus(error.message, "error"));

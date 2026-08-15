const API_PREFIX = "/api/h3-character-ref-builder";
const pageSuffix = /\/character-manager\/?$/;
const basePath = window.location.pathname.replace(pageSuffix, "");
const apiUrl = (path) => `${basePath}${API_PREFIX}${path}`;
const fileUrl = (path) => `${basePath}${path}`;

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
  stagedFiles: new Map(),
  objectUrls: new Map(),
  dirty: false,
  busy: false,
};

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

function setBusy(busy) {
  state.busy = busy;
  elements.saveButton.disabled = busy;
  elements.deleteButton.disabled = busy;
  elements.newButton.disabled = busy;
}

function setDirty(dirty = true) {
  state.dirty = dirty;
  elements.dirtyNote.hidden = !dirty;
}

function releaseObjectUrls() {
  for (const url of state.objectUrls.values()) URL.revokeObjectURL(url);
  state.objectUrls.clear();
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
  return askConfirm("Discard unsaved changes?", "The edits and selected replacement files will be lost.");
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

function resetMediaPreviews() {
  releaseObjectUrls();
  state.stagedFiles.clear();
  for (const card of document.querySelectorAll(".media-card")) {
    const slot = card.dataset.slot;
    const prompt = card.querySelector(".drop-prompt");
    const media = card.querySelector("img, audio");
    const storedUrl = state.current?.media_urls?.[slot];
    if (storedUrl) {
      media.src = `${fileUrl(storedUrl)}?v=${Date.now()}`;
      media.hidden = false;
      prompt.hidden = true;
    } else {
      media.removeAttribute("src");
      if (media.tagName === "AUDIO") media.load();
      media.hidden = true;
      prompt.hidden = false;
    }
  }
}

function showEditor(profile) {
  state.current = profile;
  state.dirty = false;
  elements.emptyEditor.hidden = true;
  elements.form.hidden = false;
  elements.name.value = profile.name || "";
  elements.description.value = profile.description || "";
  elements.title.textContent = profile.id ? profile.name : "New Character";
  elements.id.textContent = profile.id ? `UUID ${profile.id}` : "UUID assigned on save";
  elements.deleteButton.hidden = !profile.id;
  elements.dirtyNote.hidden = true;
  resetMediaPreviews();
  renderList();
  elements.name.focus();
}

async function selectCharacter(id) {
  if (state.busy || state.current?.id === id) return;
  if (!(await mayDiscardChanges())) return;
  try {
    showStatus("");
    const profile = await request(`/characters/${encodeURIComponent(id)}`);
    showEditor(profile);
  } catch (error) {
    showStatus(error.message, "error");
    await refreshList();
  }
}

async function refreshList(preferredId = state.current?.id) {
  state.profiles = await request("/characters");
  renderList();
  if (preferredId && state.profiles.some((profile) => profile.id === preferredId)) {
    const profile = await request(`/characters/${encodeURIComponent(preferredId)}`);
    showEditor(profile);
  } else if (!state.current && state.profiles.length) {
    const profile = await request(`/characters/${encodeURIComponent(state.profiles[0].id)}`);
    showEditor(profile);
  } else if (!state.profiles.length && !state.current?.id) {
    renderList();
  }
}

async function newCharacter() {
  if (state.busy || !(await mayDiscardChanges())) return;
  showStatus("");
  showEditor({
    id: null,
    name: "",
    description: "",
    reference_image_1: null,
    reference_image_2: null,
    reference_audio: null,
    media_urls: {},
  });
}

function stageFile(slot, file) {
  if (!file) return;
  const imageSlot = slot.startsWith("reference_image_");
  const validImageType = ["image/png", "image/jpeg", "image/webp"].includes(file.type)
    || /\.(png|jpe?g|webp)$/i.test(file.name);
  if (imageSlot && !validImageType) {
    showStatus("Images must be PNG, JPEG, or WebP.", "error");
    return;
  }
  if (!imageSlot && !(file.type.startsWith("audio/") || /\.(wav|mp3|flac|m4a|ogg|aac)$/i.test(file.name))) {
    showStatus("Audio must be WAV, MP3, FLAC, M4A, OGG, or AAC.", "error");
    return;
  }
  const previousUrl = state.objectUrls.get(slot);
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  const objectUrl = URL.createObjectURL(file);
  state.objectUrls.set(slot, objectUrl);
  state.stagedFiles.set(slot, file);
  const card = document.querySelector(`[data-slot="${slot}"]`);
  const media = card.querySelector("img, audio");
  media.src = objectUrl;
  media.hidden = false;
  if (media.tagName === "AUDIO") media.load();
  card.querySelector(".drop-prompt").hidden = true;
  showStatus("");
  setDirty();
}

async function uploadFile(characterId, slot, file) {
  const form = new FormData();
  form.append("slot", slot);
  form.append("file", file, file.name);
  return request(`/characters/${encodeURIComponent(characterId)}/media`, {
    method: "POST",
    body: form,
  });
}

function validateBeforeSave() {
  const name = elements.name.value.trim();
  if (!name) throw new Error("Character name is required.");
  const duplicate = state.profiles.find(
    (profile) => profile.id !== state.current?.id && profile.name.toLocaleLowerCase() === name.toLocaleLowerCase(),
  );
  if (duplicate) throw new Error(`A character named "${name}" already exists.`);
  for (const slot of ["reference_image_1", "reference_image_2", "reference_audio"]) {
    if (!state.current?.[slot] && !state.stagedFiles.has(slot)) {
      throw new Error(`Please assign ${slot.replaceAll("_", " ")} before saving.`);
    }
  }
  return name;
}

async function saveCharacter(event) {
  event.preventDefault();
  if (state.busy) return;
  let createdId = null;
  try {
    const name = validateBeforeSave();
    setBusy(true);
    showStatus("Saving character…");
    const body = JSON.stringify({ name, description: elements.description.value });
    let profile;
    if (state.current.id) {
      profile = await request(`/characters/${encodeURIComponent(state.current.id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body,
      });
    } else {
      profile = await request("/characters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      createdId = profile.id;
      state.current = profile;
    }
    for (const [slot, file] of state.stagedFiles) {
      profile = await uploadFile(profile.id, slot, file);
    }
    setDirty(false);
    await refreshList(profile.id);
    showStatus(`Saved ${profile.name}. ComfyUI character dropdowns will refresh when focused.`, "success");
  } catch (error) {
    showStatus(
      createdId
        ? `${error.message} The profile was created; correct the media and save again.`
        : error.message,
      "error",
    );
    if (createdId) await refreshList(createdId);
  } finally {
    setBusy(false);
  }
}

async function deleteCharacter() {
  if (!state.current?.id || state.busy) return;
  const confirmed = await askConfirm(
    `Delete ${state.current.name}?`,
    "This permanently removes the profile and all three managed media files. Saved workflows using its UUID will report that the profile no longer exists.",
  );
  if (!confirmed) return;
  try {
    setBusy(true);
    await request(`/characters/${encodeURIComponent(state.current.id)}`, { method: "DELETE" });
    releaseObjectUrls();
    state.current = null;
    state.dirty = false;
    elements.form.hidden = true;
    elements.emptyEditor.hidden = false;
    await refreshList();
    showStatus("Character deleted.", "success");
  } catch (error) {
    showStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

for (const input of [elements.name, elements.description]) {
  input.addEventListener("input", () => {
    if (input === elements.name) elements.title.textContent = input.value.trim() || "New Character";
    setDirty();
  });
}

for (const card of document.querySelectorAll(".media-card")) {
  const input = card.querySelector('input[type="file"]');
  card.querySelector(".choose-file").addEventListener("click", () => input.click());
  input.addEventListener("change", () => stageFile(card.dataset.slot, input.files[0]));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") input.click();
  });
  for (const eventName of ["dragenter", "dragover"]) {
    card.addEventListener(eventName, (event) => {
      event.preventDefault();
      card.classList.add("dragging");
    });
  }
  for (const eventName of ["dragleave", "drop"]) {
    card.addEventListener(eventName, (event) => {
      event.preventDefault();
      card.classList.remove("dragging");
    });
  }
  card.addEventListener("drop", (event) => stageFile(card.dataset.slot, event.dataTransfer.files[0]));
}

elements.newButton.addEventListener("click", newCharacter);
elements.form.addEventListener("submit", saveCharacter);
elements.deleteButton.addEventListener("click", deleteCharacter);
window.addEventListener("beforeunload", (event) => {
  if (state.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

refreshList().catch((error) => showStatus(error.message, "error"));

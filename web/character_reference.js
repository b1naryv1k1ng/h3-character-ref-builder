import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "H3CharacterReference";
const API_PATH = "/api/h3-character-ref-builder/characters";

let charactersById = new Map();
let refreshPromise = null;

function characterLabel(value) {
  if (!value) return "No characters available";
  return charactersById.get(String(value)) || `Missing profile (${value})`;
}

function findCharacterWidget(node) {
  return node.widgets?.find((widget) => widget.name === "character");
}

function applyCharactersToNode(node, characters) {
  if (node.comfyClass !== NODE_TYPE && node.type !== NODE_TYPE) return;
  const widget = findCharacterWidget(node);
  if (!widget) return;
  const current = typeof widget.value === "string" ? widget.value : String(widget.value ?? "");
  const ids = characters.map((character) => character.id);
  if (current && !ids.includes(current)) ids.unshift(current);
  if (!ids.length) ids.push("");
  widget.options ||= {};
  widget.options.values = ids;
  widget.options.getOptionLabel = characterLabel;
  if (!current && characters.length) widget.value = characters[0].id;
  node.setDirtyCanvas?.(true, true);
}

async function fetchCharacters() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const response = await api.fetchApi(API_PATH, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok || !Array.isArray(payload.data)) {
      throw new Error(payload?.error?.message || "Could not load H3 character profiles.");
    }
    charactersById = new Map(payload.data.map((character) => [character.id, character.name]));
    return payload.data;
  })();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

async function refreshNode(node) {
  try {
    applyCharactersToNode(node, await fetchCharacters());
  } catch (error) {
    console.error("[H3 Character Ref Builder]", error);
  }
}

async function refreshAllNodes() {
  try {
    const characters = await fetchCharacters();
    for (const node of app.graph?._nodes || []) applyCharactersToNode(node, characters);
  } catch (error) {
    console.error("[H3 Character Ref Builder]", error);
  }
}

function openManager() {
  const url = typeof api.fileURL === "function"
    ? api.fileURL("/character-manager")
    : new URL(
        location.pathname.replace(/\/$/, "") + "/character-manager",
        location.origin,
      ).href;
  window.open(url, "_blank", "noopener");
}

app.registerExtension({
  name: "h3.character-ref-builder",
  commands: [
    {
      id: "h3.open-character-manager",
      label: "H3 Character Manager",
      icon: "pi pi-users",
      function: openManager,
    },
  ],
  menuCommands: [
    {
      path: ["Extensions", "H3 Character Ref Builder"],
      commands: ["h3.open-character-manager"],
    },
  ],
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_TYPE) return;
    const originalCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function (...args) {
      const result = originalCreated?.apply(this, args);
      void refreshNode(this);
      return result;
    };
    const originalMenu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (_, options) {
      const result = originalMenu?.apply(this, arguments);
      options.push({ content: "Open H3 Character Manager", callback: openManager });
      return result;
    };
  },
  async setup() {
    window.addEventListener("focus", refreshAllNodes);
    await refreshAllNodes();
  },
});

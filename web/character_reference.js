import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "H3CharacterReference";
const API_PREFIX = "/api/h3-character-ref-builder";
const NO_SCENE = "__h3_no_scene_preset__";

let charactersById = new Map();
let scenesById = new Map();
let refreshPromise = null;

function labelForCharacter(value) {
  if (!value) return "No characters available";
  return charactersById.get(String(value)) || `Missing profile (${value})`;
}

function labelForScene(value) {
  if (value === NO_SCENE) return "(No Scene Preset)";
  return scenesById.get(String(value)) || `Missing scene (${value})`;
}

const WIDGET_LABELS = Object.freeze({
  character: "Character",
  scene: "Scene Preset",
  detailed_description: "Video / Action Description",
  overall_soundscape: "Additional Soundscape",
  non_diegetic_music: "Non-Diegetic Music",
});

function applyWidgetLabels(node) {
  for (const [name, label] of Object.entries(WIDGET_LABELS)) {
    const widget = findWidget(node, name);
    if (widget) widget.label = label;
  }
}

function findWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function applyOptions(node, widgetName, items, fallback, labeler, chooseFirst) {
  if (node.comfyClass !== NODE_TYPE && node.type !== NODE_TYPE) return;
  const widget = findWidget(node, widgetName);
  if (!widget) return;
  const current = typeof widget.value === "string" ? widget.value : String(widget.value ?? "");
  const values = items.map((item) => item.id);
  if (fallback && !values.includes(fallback)) values.unshift(fallback);
  if (current && !values.includes(current)) values.unshift(current);
  if (!values.length) values.push("");
  widget.options ||= {};
  widget.options.values = values;
  widget.options.getOptionLabel = labeler;
  if (!current) widget.value = chooseFirst && items.length ? items[0].id : fallback;
  node.setDirtyCanvas?.(true, true);
}

function applyCatalogs(node, catalogs) {
  applyWidgetLabels(node);
  applyOptions(node, "character", catalogs.characters, "", labelForCharacter, true);
  applyOptions(node, "scene", catalogs.scenes, NO_SCENE, labelForScene, false);
}

async function fetchCatalogs() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const [characterResponse, sceneResponse] = await Promise.all([
      api.fetchApi(`${API_PREFIX}/characters`, { cache: "no-store" }),
      api.fetchApi(`${API_PREFIX}/scenes`, { cache: "no-store" }),
    ]);
    const [characters, scenes] = await Promise.all([
      characterResponse.json(),
      sceneResponse.json(),
    ]);
    if (!characterResponse.ok || !characters.ok || !Array.isArray(characters.data)) {
      throw new Error(characters?.error?.message || "Could not load H3 character profiles.");
    }
    if (!sceneResponse.ok || !scenes.ok || !Array.isArray(scenes.data)) {
      throw new Error(scenes?.error?.message || "Could not load H3 Scene Presets.");
    }
    charactersById = new Map(characters.data.map((item) => [item.id, item.name]));
    scenesById = new Map(scenes.data.map((item) => [item.id, item.name]));
    return { characters: characters.data, scenes: scenes.data };
  })();
  try {
    return await refreshPromise;
  } finally {
    refreshPromise = null;
  }
}

async function refreshNode(node) {
  try {
    applyCatalogs(node, await fetchCatalogs());
  } catch (error) {
    console.error("[H3 Character Ref Builder]", error);
  }
}

async function refreshAllNodes() {
  try {
    const catalogs = await fetchCatalogs();
    for (const node of app.graph?._nodes || []) applyCatalogs(node, catalogs);
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
      label: "H3 Reference Manager",
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
      applyWidgetLabels(this);
      void refreshNode(this);
      return result;
    };
    const originalMenu = nodeType.prototype.getExtraMenuOptions;
    nodeType.prototype.getExtraMenuOptions = function (_, options) {
      const result = originalMenu?.apply(this, arguments);
      options.push({ content: "Open H3 Reference Manager", callback: openManager });
      return result;
    };
  },
  async setup() {
    window.addEventListener("focus", refreshAllNodes);
    await refreshAllNodes();
  },
});

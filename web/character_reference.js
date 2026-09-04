import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyButton } from "../../scripts/ui/components/button.js";

const SINGLE_NODE_TYPE = "H3CharacterReference";
const DUAL_NODE_TYPE = "H3DualCharacterReference";
const REFERENCE_NODE_TYPES = new Set([SINGLE_NODE_TYPE, DUAL_NODE_TYPE]);
const API_PREFIX = "/api/h3-character-ref-builder";
const NO_SCENE = "__h3_no_scene_preset__";
const NO_PROP = "__h3_no_prop_reference__";
const TOPBAR_BUTTON_ID = "h3-character-manager-topbar-button";

let charactersById = new Map();
let scenesById = new Map();
let propsById = new Map();
let refreshPromise = null;

function labelForCharacter(value) {
  if (!value) return "No characters available";
  return charactersById.get(String(value)) || `Missing profile (${value})`;
}

function labelForScene(value) {
  if (value === NO_SCENE) return "(No Scene Preset)";
  return scenesById.get(String(value)) || `Missing scene (${value})`;
}

function labelForProp(value) {
  if (value === NO_PROP) return "(No Prop Reference)";
  return propsById.get(String(value)) || `Missing prop (${value})`;
}

const SINGLE_WIDGET_LABELS = Object.freeze({
  character: "Character",
  scene: "Scene Preset",
  prop: "Prop Reference",
});
const DUAL_WIDGET_LABELS = Object.freeze({
  character_1: "Character 1",
  character_2: "Character 2",
  scene: "Scene Preset",
  prop: "Prop Reference",
});

function nodeClass(node) {
  return node.comfyClass || node.type;
}

function isReferenceNode(node) {
  return REFERENCE_NODE_TYPES.has(nodeClass(node));
}

function applyWidgetLabels(node) {
  const labels = nodeClass(node) === DUAL_NODE_TYPE ? DUAL_WIDGET_LABELS : SINGLE_WIDGET_LABELS;
  for (const [name, label] of Object.entries(labels)) {
    const widget = findWidget(node, name);
    if (widget) widget.label = label;
  }
}

function findWidget(node, name) {
  return node.widgets?.find((widget) => widget.name === name);
}

function applyOptions(node, widgetName, items, fallback, labeler, chooseFirst) {
  if (!isReferenceNode(node)) return;
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
  if (!isReferenceNode(node)) return;
  applyWidgetLabels(node);
  if (nodeClass(node) === DUAL_NODE_TYPE) {
    applyOptions(node, "character_1", catalogs.characters, "", labelForCharacter, true);
    applyOptions(node, "character_2", catalogs.characters, "", labelForCharacter, true);
  } else {
    applyOptions(node, "character", catalogs.characters, "", labelForCharacter, true);
  }
  applyOptions(node, "scene", catalogs.scenes, NO_SCENE, labelForScene, false);
  applyOptions(node, "prop", catalogs.props, NO_PROP, labelForProp, false);
}

async function fetchCatalogs() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const [characterResponse, sceneResponse, propResponse] = await Promise.all([
      api.fetchApi(`${API_PREFIX}/characters`, { cache: "no-store" }),
      api.fetchApi(`${API_PREFIX}/scenes`, { cache: "no-store" }),
      api.fetchApi(`${API_PREFIX}/props`, { cache: "no-store" }),
    ]);
    const [characters, scenes, props] = await Promise.all([
      characterResponse.json(),
      sceneResponse.json(),
      propResponse.json(),
    ]);
    if (!characterResponse.ok || !characters.ok || !Array.isArray(characters.data)) {
      throw new Error(characters?.error?.message || "Could not load H3 character profiles.");
    }
    if (!sceneResponse.ok || !scenes.ok || !Array.isArray(scenes.data)) {
      throw new Error(scenes?.error?.message || "Could not load H3 Scene Presets.");
    }
    if (!propResponse.ok || !props.ok || !Array.isArray(props.data)) {
      throw new Error(props?.error?.message || "Could not load H3 Prop References.");
    }
    charactersById = new Map(characters.data.map((item) => [item.id, item.name]));
    scenesById = new Map(scenes.data.map((item) => [item.id, item.name]));
    const usableProps = props.data.filter((item) => item.usable);
    propsById = new Map(usableProps.map((item) => [item.id, item.name]));
    return { characters: characters.data, scenes: scenes.data, props: usableProps };
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
  window.open(url, "_blank", "noopener,noreferrer");
}

function registerManagerTopbarButton() {
  const buttonGroup = app.menu?.settingsGroup;
  if (!buttonGroup?.append) {
    console.warn(
      "[H3 Character Ref Builder] ComfyUI top-bar button API is unavailable.",
    );
    return;
  }

  const isRegistered = buttonGroup.buttons?.some((item) => {
    const element = item?.element ?? item;
    return element?.id === TOPBAR_BUTTON_ID;
  });
  if (isRegistered || document.getElementById(TOPBAR_BUTTON_ID)) return;

  const button = new ComfyButton({
    icon: "account-multiple",
    tooltip: "Character Manager",
    action: openManager,
  });
  button.element.id = TOPBAR_BUTTON_ID;
  buttonGroup.append(button);
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
    if (!REFERENCE_NODE_TYPES.has(nodeData.name)) return;
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
    registerManagerTopbarButton();
    window.addEventListener("focus", refreshAllNodes);
    await refreshAllNodes();
  },
});

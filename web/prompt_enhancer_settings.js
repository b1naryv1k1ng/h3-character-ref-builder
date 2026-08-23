import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const API_PREFIX = "/api/h3-character-ref-builder/prompt-enhancer";
const SETTINGS_CATEGORY = "H3 Character Ref Builder";
const SETTINGS_SUBCATEGORY = "Prompt Enhancer";

let configStatus = null;
let statusRequest = null;

function settingCategory(name) {
  return [SETTINGS_CATEGORY, SETTINGS_SUBCATEGORY, name];
}

function controlInput(type = "text") {
  const input = document.createElement("input");
  input.type = type;
  input.className = "p-inputtext p-component";
  input.disabled = true;
  return input;
}

function controlButton(label) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = "p-button p-component p-button-sm";
  return button;
}

function validateStatus(data) {
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("The Prompt Enhancer configuration response was invalid.");
  }
  if (Object.hasOwn(data, "api_key")) {
    throw new Error("The Prompt Enhancer configuration response was unsafe.");
  }
  const required = [
    "base_url",
    "model",
    "timeout_seconds",
    "api_key_configured",
    "api_key_source",
  ];
  if (required.some((field) => !Object.hasOwn(data, field))) {
    throw new Error("The Prompt Enhancer configuration response was incomplete.");
  }
  return data;
}

async function requestJson(path, options = {}) {
  const response = await api.fetchApi(`${API_PREFIX}${path}`, {
    cache: "no-store",
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The Prompt Enhancer configuration server returned invalid JSON.");
  }
  if (!response.ok || !payload?.ok) {
    throw new Error(
      payload?.error?.message || "Could not update Prompt Enhancer configuration.",
    );
  }
  configStatus = validateStatus(payload.data);
  return configStatus;
}

function refreshConfigStatus() {
  if (!statusRequest) {
    statusRequest = requestJson("/config").finally(() => {
      statusRequest = null;
    });
  }
  return statusRequest;
}

async function saveProviderConfig() {
  if (!configStatus) await refreshConfigStatus();
  return requestJson("/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_url: configStatus.base_url,
      model: configStatus.model,
      timeout_seconds: Number(configStatus.timeout_seconds),
    }),
  });
}

function createProviderInput(field, type = "text") {
  const input = controlInput(type);
  if (field === "timeout_seconds") {
    input.min = "1";
    input.max = "300";
    input.step = "1";
    input.inputMode = "numeric";
  }

  void refreshConfigStatus()
    .then((status) => {
      input.value = String(status[field]);
      input.disabled = false;
    })
    .catch((error) => {
      input.title = error.message;
      input.setCustomValidity(error.message);
    });

  input.addEventListener("input", () => {
    if (!configStatus) return;
    configStatus[field] = field === "timeout_seconds"
      ? Number(input.value)
      : input.value;
    input.setCustomValidity("");
  });
  input.addEventListener("change", async () => {
    input.disabled = true;
    try {
      const status = await saveProviderConfig();
      input.value = String(status[field]);
      input.setCustomValidity("");
      input.title = "Saved";
    } catch (error) {
      input.setCustomValidity(error.message);
      input.title = error.message;
      input.reportValidity();
    } finally {
      input.disabled = false;
    }
  });
  return input;
}

function createApiKeyControl() {
  const container = document.createElement("div");
  container.style.display = "grid";
  container.style.gap = "0.4rem";
  container.style.minWidth = "18rem";

  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "0.4rem";
  row.style.alignItems = "center";

  const input = controlInput("password");
  input.autocomplete = "new-password";
  input.placeholder = "Enter new API key";
  input.setAttribute("aria-label", "New Prompt Enhancer API key");

  const saveButton = controlButton("Save API Key");
  const clearButton = controlButton("Clear");
  saveButton.disabled = true;
  clearButton.disabled = true;

  const statusText = document.createElement("span");
  statusText.style.fontSize = "0.8rem";
  statusText.style.opacity = "0.8";

  function renderStatus(status) {
    statusText.textContent = status.api_key_configured
      ? `Configured — ${status.api_key_source}`
      : "Not configured";
    saveButton.textContent = status.api_key_configured
      ? "Replace API Key"
      : "Save API Key";
    clearButton.disabled = status.api_key_source !== "Saved configuration";
    input.disabled = false;
    saveButton.disabled = false;
  }

  void refreshConfigStatus().then(renderStatus).catch((error) => {
    statusText.textContent = error.message;
  });

  saveButton.addEventListener("click", async () => {
    const apiKey = input.value.trim();
    if (!apiKey) {
      statusText.textContent = "Enter a non-empty API key.";
      return;
    }
    input.disabled = true;
    saveButton.disabled = true;
    clearButton.disabled = true;
    statusText.textContent = "Saving…";
    try {
      const status = await requestJson("/api-key", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      input.value = "";
      renderStatus(status);
    } catch (error) {
      input.value = "";
      statusText.textContent = error.message;
      input.disabled = false;
      saveButton.disabled = false;
    }
  });

  clearButton.addEventListener("click", async () => {
    input.value = "";
    input.disabled = true;
    saveButton.disabled = true;
    clearButton.disabled = true;
    statusText.textContent = "Clearing…";
    try {
      renderStatus(await requestJson("/api-key", { method: "DELETE" }));
    } catch (error) {
      statusText.textContent = error.message;
      input.disabled = false;
      saveButton.disabled = false;
      clearButton.disabled = false;
    }
  });

  row.append(input, saveButton, clearButton);
  container.append(row, statusText);
  return container;
}

app.registerExtension({
  name: "h3.character-ref-builder.prompt-enhancer-settings",
  settings: [
    {
      id: "H3.CharacterRefBuilder.PromptEnhancer.BaseURL",
      name: "API Base URL",
      category: settingCategory("API Base URL"),
      tooltip: "OpenAI-compatible API base URL.",
      type: () => createProviderInput("base_url"),
      defaultValue: "",
    },
    {
      id: "H3.CharacterRefBuilder.PromptEnhancer.Model",
      name: "API Model",
      category: settingCategory("API Model"),
      tooltip: "Editable provider model identifier.",
      type: () => createProviderInput("model"),
      defaultValue: "",
    },
    {
      id: "H3.CharacterRefBuilder.PromptEnhancer.Timeout",
      name: "Request Timeout",
      category: settingCategory("Request Timeout"),
      tooltip: "Provider request timeout in seconds (1–300).",
      type: () => createProviderInput("timeout_seconds", "number"),
      defaultValue: "",
    },
    {
      id: "H3.CharacterRefBuilder.PromptEnhancer.ApiKey",
      name: "API Key",
      category: settingCategory("API Key"),
      tooltip: "Write-only server credential. The saved value is never returned.",
      type: createApiKeyControl,
      defaultValue: "",
      telemetry: { trackChanges: false, includeValues: false },
    },
  ],
});

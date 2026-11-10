const query = document.querySelector("#q");

document.addEventListener("keydown", (event) => {
  const tag = (event.target && event.target.tagName) || "";
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || event.target.isContentEditable;
  if (event.key === "/" && !typing && query) {
    event.preventDefault();
    query.focus();
    query.select();
  }
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && tag === "TEXTAREA") {
    event.preventDefault();
    const form = event.target.form;
    if (form && typeof form.requestSubmit === "function") form.requestSubmit();
  }
});

const starter = document.querySelector("#persona-starter");
const soul = document.querySelector("textarea[name=soul]");
if (starter && soul) {
  starter.addEventListener("click", () => {
    if (!soul.value.trim()) {
      soul.value = "Be precise. Have a take when the evidence supports it.\nNo filler. No invented facts. No secrets.\nProject conventions beat generic advice.";
    }
    soul.focus();
  });
}

const provider = document.querySelector("#provider");
const baseUrl = document.querySelector("#base_url");
const modelChoice = document.querySelector("#model_choice");
const modelCustom = document.querySelector("#model_custom");
const apiKey = document.querySelector("#api_key");
const modelFilter = document.querySelector("#model_filter");
const modelsStatus = document.querySelector("#models-status");
const modelsRefresh = document.querySelector("#models-refresh");
const settingsForm = document.querySelector("#settings-form");

const byProvider = new Map();

function rememberOption(option) {
  const key = option.dataset.provider || "";
  if (!byProvider.has(key)) byProvider.set(key, []);
  byProvider.get(key).push({
    value: option.value,
    label: option.textContent,
    provider: option.dataset.provider || "",
    url: option.dataset.url || "",
  });
}

if (modelChoice) {
  Array.from(modelChoice.options).forEach(rememberOption);
}

function setStatus(kind, text) {
  if (!modelsStatus) return;
  modelsStatus.textContent = text || "";
  modelsStatus.classList.toggle("is-error", kind === "error");
}

function renderModels(keepValue) {
  if (!modelChoice) return;
  const key = provider ? provider.value : "";
  const needle = (modelFilter && modelFilter.value ? modelFilter.value : "").trim().toLowerCase();
  const rows = (byProvider.get(key) || []).filter((row) => {
    if (!needle || row.value === "__custom__") return true;
    return row.label.toLowerCase().includes(needle) || row.value.toLowerCase().includes(needle);
  });
  const custom = (byProvider.get("") || []).find((row) => row.value === "__custom__");
  modelChoice.innerHTML = "";
  rows.forEach((row) => {
    if (row.value === "__custom__") return;
    const option = document.createElement("option");
    option.value = row.value;
    option.textContent = row.label;
    option.dataset.provider = row.provider;
    option.dataset.url = row.url;
    modelChoice.appendChild(option);
  });
  if (custom) {
    const option = document.createElement("option");
    option.value = "__custom__";
    option.textContent = custom.label;
    modelChoice.appendChild(option);
  }
  if (keepValue && Array.from(modelChoice.options).some((option) => option.value === keepValue)) {
    modelChoice.value = keepValue;
  }
}

let fetchGen = 0;
let fetchTimer = 0;

function loadModels(force) {
  if (!provider || !settingsForm) return;
  const info = provider.selectedOptions[0];
  const typed = apiKey ? apiKey.value.trim() : "";
  const saved = settingsForm.dataset.savedProvider || "";
  const keySet = settingsForm.dataset.keySet === "1";
  const needsKey = info && info.dataset.requiresKey === "1";
  const isPublic = info && info.dataset.modelsPublic === "1";
  const canUseStored = keySet && saved === provider.value;
  if (!force && typed && typed.length < 8) return;
  if (needsKey && !isPublic && !typed && !canUseStored) {
    setStatus("idle", modelsStatus ? modelsStatus.dataset.empty : "");
    return;
  }
  const gen = ++fetchGen;
  setStatus("loading", modelsStatus ? modelsStatus.dataset.loading : "");
  const body = new FormData();
  body.set("provider", provider.value);
  body.set("base_url", baseUrl ? baseUrl.value : "");
  body.set("api_key", typed);
  fetch("/api/models", { method: "POST", body })
    .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
    .then(({ ok, data }) => {
      if (gen !== fetchGen) return;
      const models = (data && data.models) || [];
      if (models.length) {
        const url = (info && info.dataset.url) || (baseUrl ? baseUrl.value : "");
        byProvider.set(
          provider.value,
          models.map((row) => ({
            value: row.id,
            label: row.label || row.id,
            provider: provider.value,
            url,
          })),
        );
        const customTyped = modelCustom && modelCustom.value.trim();
        const current = modelChoice ? modelChoice.value : "";
        renderModels(customTyped ? "__custom__" : current);
        if (!customTyped && current && current !== "__custom__" && !models.some((row) => row.id === current)) {
          if (modelCustom && !modelCustom.value) modelCustom.value = current;
          if (modelChoice) modelChoice.value = "__custom__";
        }
      }
      if (!ok || (data && data.error)) {
        setStatus("error", (data && data.error) || (modelsStatus ? modelsStatus.dataset.failed : ""));
        return;
      }
      const ready = modelsStatus ? modelsStatus.dataset.ready || "" : "";
      setStatus("ok", ready.replace("{count}", String(models.length)));
    })
    .catch(() => {
      if (gen !== fetchGen) return;
      setStatus("error", modelsStatus ? modelsStatus.dataset.failed : "");
    });
}

if (provider && baseUrl) {
  provider.addEventListener("change", () => {
    const url = provider.selectedOptions[0] && provider.selectedOptions[0].dataset.url;
    if (url) baseUrl.value = url;
    if (modelFilter) modelFilter.value = "";
    renderModels("");
    loadModels(false);
  });
}

if (modelChoice && modelCustom) {
  renderModels(modelChoice.value);
  modelChoice.addEventListener("change", () => {
    const option = modelChoice.selectedOptions[0];
    if (!option || option.value === "__custom__") {
      modelCustom.focus();
      return;
    }
    modelCustom.value = "";
    if (provider && option.dataset.provider && provider.value !== option.dataset.provider) {
      provider.value = option.dataset.provider;
    }
    if (baseUrl && option.dataset.url) baseUrl.value = option.dataset.url;
  });
}

if (apiKey) {
  apiKey.addEventListener("input", () => {
    window.clearTimeout(fetchTimer);
    fetchTimer = window.setTimeout(() => loadModels(false), 600);
  });
  apiKey.addEventListener("change", () => loadModels(true));
}

if (modelsRefresh) modelsRefresh.addEventListener("click", () => loadModels(true));
if (modelFilter) {
  modelFilter.addEventListener("input", () => renderModels(modelChoice ? modelChoice.value : ""));
}
if (provider) loadModels(false);

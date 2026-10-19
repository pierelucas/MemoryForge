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

const provider = document.querySelector("#provider");
const baseUrl = document.querySelector("#base_url");
const modelChoice = document.querySelector("#model_choice");
const modelCustom = document.querySelector("#model_custom");

if (provider && baseUrl) {
  provider.addEventListener("change", () => {
    const url = provider.selectedOptions[0]?.dataset.url || "";
    if (url) baseUrl.value = url;
  });
}

if (modelChoice && modelCustom) {
  modelChoice.addEventListener("change", () => {
    const option = modelChoice.selectedOptions[0];
    if (!option || option.value === "__custom__") {
      modelCustom.focus();
      return;
    }
    modelCustom.value = "";
    if (provider && option.dataset.provider) provider.value = option.dataset.provider;
    if (baseUrl && option.dataset.url) baseUrl.value = option.dataset.url;
  });
}

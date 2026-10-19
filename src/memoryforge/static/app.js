const query = document.querySelector("#q");
if (query && query.form) {
  let timer = 0;
  query.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      if (typeof query.form.requestSubmit === "function") query.form.requestSubmit();
    }, 280);
  });
}

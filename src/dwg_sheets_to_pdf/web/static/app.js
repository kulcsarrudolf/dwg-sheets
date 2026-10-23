// The little the page needs beyond htmx: drag and drop, a size check before uploading, and upload progress.
(() => {
  const form = document.getElementById("upload");
  if (!form) return;
  const input = form.querySelector("#file");
  const bar = form.querySelector(".upload-bar > span");

  // Dropping a file anywhere on the zone picks it, as choosing it would.
  ["dragenter", "dragover"].forEach((type) =>
    form.addEventListener(type, (e) => { e.preventDefault(); form.classList.add("over"); }));
  ["dragleave", "drop"].forEach((type) =>
    form.addEventListener(type, (e) => { e.preventDefault(); form.classList.remove("over"); }));
  form.addEventListener("drop", (e) => {
    if (!e.dataTransfer.files.length) return;
    input.files = e.dataTransfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  // A file dropped outside the zone should not open in the tab.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  // Remember the chosen output for next time (the form only sends when a file is chosen).
  form.querySelectorAll('input[name="images"]').forEach((radio) =>
    radio.addEventListener("change", () => {
      document.cookie = `images=${radio.value}; path=/; max-age=31536000; samesite=lax`;
    }));

  // Refuse a wrong or too large file before sending it; the server checks again.
  form.addEventListener("htmx:confirm", (e) => {
    const file = input.files[0];
    let problem = "";
    if (!file) problem = " ";
    else if (!/\.(dwg|dxf)$/i.test(file.name)) problem = form.dataset.badType;
    else if (file.size > Number(form.dataset.maxBytes)) problem = form.dataset.tooLarge;
    if (!problem) return;
    e.preventDefault();
    input.value = "";
    if (problem.trim()) {
      const alert = document.createElement("div");
      alert.className = "alert";
      alert.setAttribute("role", "alert");
      alert.textContent = problem;
      document.getElementById("job").replaceChildren(alert);
    }
  });

  form.addEventListener("htmx:xhr:progress", (e) => {
    if (e.detail.lengthComputable) bar.style.width = `${Math.round((e.detail.loaded / e.detail.total) * 100)}%`;
  });
  form.addEventListener("htmx:beforeRequest", () => { bar.style.width = "0%"; form.classList.add("uploading"); });
  form.addEventListener("htmx:afterRequest", () => { form.classList.remove("uploading"); input.value = ""; });
})();

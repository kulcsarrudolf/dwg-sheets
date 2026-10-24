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

// Ticking sheets to download a few. The list is redrawn while sheets plot, so the ticks live here and are
// put back after each redraw. Shift-click ticks a range; Escape clears. Without this script the form still
// works: tick boxes and press the button.
(() => {
  const picked = new Set();
  let job = null;
  let last = null; // the box clicked last, for shift-click ranges

  const form = () => document.getElementById("pick-form");
  const boxes = (f) => [...f.querySelectorAll('input[name="sheet"]')];

  function sync() {
    const f = form();
    if (!f) return;
    if (f.dataset.job !== job) {
      job = f.dataset.job;
      picked.clear();
      last = null;
    }
    const all = boxes(f);
    for (const box of all) {
      box.checked = picked.has(box.value);
      box.closest(".card").classList.toggle("is-picked", box.checked);
    }
    const n = picked.size;
    f.classList.toggle("selecting", n > 0);
    f.querySelector("[data-selbar]").hidden = n === 0;
    f.querySelector("[data-count]").textContent = n.toLocaleString(document.documentElement.lang);
    const every = f.querySelector("[data-select-all]");
    if (every) {
      every.checked = n > 0 && n === all.length;
      every.indeterminate = n > 0 && n < all.length;
    }
  }

  function set(box, on) {
    if (on) picked.add(box.value);
    else picked.delete(box.value);
  }

  document.addEventListener("click", (e) => {
    const box = e.target.closest?.('#pick-form input[name="sheet"]');
    if (box && e.shiftKey && last) {
      const all = boxes(form());
      const [a, b] = [all.indexOf(last), all.indexOf(box)].sort((x, y) => x - y);
      if (a >= 0) all.slice(a, b + 1).forEach((other) => set(other, box.checked));
      window.getSelection()?.removeAllRanges();
    }
    if (e.target.closest?.("[data-clear]")) {
      picked.clear();
      sync();
    }
  });

  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.matches('#pick-form input[name="sheet"]')) {
      set(t, t.checked);
      last = t;
      sync();
    } else if (t.matches("[data-select-all]")) {
      boxes(form()).forEach((box) => set(box, t.checked));
      sync();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && picked.size) {
      picked.clear();
      sync();
    }
  });

  // The redrawn list has new boxes: point `last` at the new copy of the same sheet.
  document.addEventListener("htmx:afterSettle", () => {
    if (last) last = form()?.querySelector(`#${last.id}`) ?? null;
    sync();
  });
  sync();
})();

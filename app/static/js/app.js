// Theme toggle (persisted)
(function () {
  const saved = localStorage.getItem("ams-theme");
  if (saved) document.documentElement.dataset.theme = saved;
  const btn = document.getElementById("themeToggle");
  if (btn) btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("ams-theme", next);
  });
})();

function csrfToken() {
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.content : "";
}

function showToast(message, kind) {
  const box = document.getElementById("toastBox");
  if (!box) return;
  const el = document.createElement("div");
  el.className = `toast show align-items-center text-bg-${kind || "info"} border-0 mb-2`;
  el.innerHTML = `<div class="d-flex"><div class="toast-body"></div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>`;
  el.querySelector(".toast-body").textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// Drag & drop + upload progress (workspace page)
(function () {
  const dz = document.getElementById("dropzone");
  const input = document.getElementById("videoInput");
  const form = document.getElementById("uploadForm");
  if (!dz || !input || !form) return;
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  ["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("dragging"); }));
  dz.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; form.requestSubmit(); } });
  input.addEventListener("change", () => { if (input.files.length) form.requestSubmit(); });
  form.addEventListener("submit", () => {
    const wrap = document.getElementById("uploadProgressWrap");
    if (wrap) wrap.classList.remove("d-none");
  });
})();

// Live job polling (job page): uses the JSON API; progress is real per-clip data.
(function () {
  const el = document.getElementById("jobStatus");
  if (!el) return;
  const jobId = el.dataset.jobId;
  const bar = document.getElementById("jobProgressBar");
  const label = document.getElementById("jobStatusLabel");
  async function poll() {
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { headers: { "Accept": "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      const job = data.job;
      if (bar) { bar.style.width = job.progress + "%"; bar.textContent = job.progress + "%"; }
      if (label) label.textContent = job.status;
      if (["completed", "failed", "cancelled"].includes(job.status)) {
        if (job.status === "completed") location.reload();
        return;
      }
      setTimeout(poll, 2000);
    } catch (_) { setTimeout(poll, 4000); }
  }
  const status = el.dataset.status;
  if (["queued", "processing"].includes(status)) poll();
})();

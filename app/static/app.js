const state = {
  file: null,
  sourceUrl: null,
  resultUrl: null,
  manualColor: false,
  processingController: null,
};

const $ = (selector) => document.querySelector(selector);
const fileInput = $("#fileInput");
const dropzone = $("#dropzone");
const emptyState = $("#emptyState");
const previewState = $("#previewState");
const sourcePreview = $("#sourcePreview");
const resultPreview = $("#resultPreview");
const resultPlaceholder = $("#resultPlaceholder");
const loader = $("#loader");
const processButton = $("#processButton");
const downloadButton = $("#downloadButton");
const errorBox = $("#errorBox");
const jobInfo = $("#jobInfo");

function humanSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

function revoke(url) {
  if (url) URL.revokeObjectURL(url);
}

function clearResult() {
  revoke(state.resultUrl);
  state.resultUrl = null;
  resultPreview.removeAttribute("src");
  resultPreview.hidden = true;
  resultPlaceholder.hidden = false;
  downloadButton.hidden = true;
  jobInfo.textContent = "";
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function acceptFile(file) {
  showError("");
  if (!file || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    showError("Choisis une image PNG, JPEG ou WebP.");
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    showError("Cette image dépasse la limite de 15 Mo.");
    return;
  }

  state.file = file;
  revoke(state.sourceUrl);
  state.sourceUrl = URL.createObjectURL(file);
  sourcePreview.src = state.sourceUrl;
  $("#fileName").textContent = file.name || "Image collée";
  $("#fileMeta").textContent = humanSize(file.size);
  emptyState.hidden = true;
  previewState.hidden = false;
  processButton.disabled = false;
  clearResult();
  void processImage();
}

function openPicker(event) {
  event.stopPropagation();
  fileInput.click();
}

$("#chooseButton").addEventListener("click", openPicker);
$("#replaceButton").addEventListener("click", openPicker);
fileInput.addEventListener("change", () => acceptFile(fileInput.files[0]));

dropzone.addEventListener("click", (event) => {
  if (emptyState.hidden || event.target.closest("button, a, input")) return;
  openPicker(event);
});
dropzone.addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && !emptyState.hidden) openPicker(event);
});

for (const eventName of ["dragenter", "dragover"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  });
}
dropzone.addEventListener("drop", (event) => acceptFile(event.dataTransfer.files[0]));

document.addEventListener("paste", (event) => {
  const item = [...event.clipboardData.items].find((entry) => entry.kind === "file" && entry.type.startsWith("image/"));
  if (item) {
    event.preventDefault();
    const pasted = item.getAsFile();
    const extension = pasted.type === "image/jpeg" ? "jpg" : pasted.type.split("/")[1];
    acceptFile(new File([pasted], `image-collee.${extension}`, { type: pasted.type }));
  }
});

const tolerance = $("#tolerance");
tolerance.addEventListener("input", () => {
  $("#toleranceValue").textContent = tolerance.value;
  clearResult();
});

$("#removeEnclosed").addEventListener("change", clearResult);

$("#autoColor").addEventListener("click", () => {
  state.manualColor = false;
  $("#autoColor").classList.add("active");
  $("#manualColor").classList.remove("active");
  $("#colorControl").hidden = true;
  clearResult();
});

$("#manualColor").addEventListener("click", () => {
  state.manualColor = true;
  $("#manualColor").classList.add("active");
  $("#autoColor").classList.remove("active");
  $("#colorControl").hidden = false;
  clearResult();
});

$("#backgroundColor").addEventListener("input", (event) => {
  $("#colorValue").textContent = event.target.value.toUpperCase();
  clearResult();
});

async function processImage() {
  if (!state.file) return;
  state.processingController?.abort();
  const controller = new AbortController();
  state.processingController = controller;
  showError("");
  clearResult();
  loader.hidden = false;
  resultPlaceholder.hidden = true;
  processButton.disabled = true;
  processButton.textContent = "Traitement…";

  const form = new FormData();
  form.append("image", state.file);
  form.append("tolerance", tolerance.value);
  form.append("background_color", state.manualColor ? $("#backgroundColor").value : "");
  form.append("remove_enclosed", $("#removeEnclosed").checked ? "true" : "false");

  try {
    const response = await fetch("/api/remove-background", {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || `Erreur serveur (${response.status})`);
    }

    const blob = await response.blob();
    state.resultUrl = URL.createObjectURL(blob);
    resultPreview.src = state.resultUrl;
    resultPreview.hidden = false;
    downloadButton.href = state.resultUrl;
    downloadButton.hidden = false;
    const jobId = response.headers.get("X-Job-ID");
    const duration = response.headers.get("X-Processing-Time-Ms");
    jobInfo.textContent = `${duration || "—"} ms · ${jobId ? jobId.slice(0, 8) : "—"}`;
  } catch (error) {
    if (error.name === "AbortError") return;
    resultPlaceholder.hidden = false;
    showError(error.message || "Le traitement a échoué.");
  } finally {
    if (state.processingController !== controller) return;
    state.processingController = null;
    loader.hidden = true;
    processButton.disabled = false;
    processButton.textContent = "Détourer l’image";
  }
}

processButton.addEventListener("click", processImage);

window.addEventListener("beforeunload", () => {
  revoke(state.sourceUrl);
  revoke(state.resultUrl);
});

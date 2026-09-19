/* Pluto web client module: composer (attachments, camera, drag-drop, mic; owns pendingFiles).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { $, toast, fmtSize } from "./ui.js";

/* Module-local element refs. Grabbed in initComposer(), not at import
 * time, so this module imports cleanly without a DOM
 * (node/vitest/smoke phase 1). app.js calls initComposer() at boot. */
var input = null, attachments = null;

/* ---------- attachments ---------- */
var composer = null, attachWrap = null, attachMenu = null,
  photoInput = null, docInput = null;
var _composerInit = false;
function initComposer() {
  if (_composerInit) return;
  _composerInit = true;
  input = $("input"); attachments = $("attachments");
  composer = $("composer"); attachWrap = $("attachWrap"); attachMenu = $("attachMenu");
  photoInput = $("photoInput"); docInput = $("docInput");
  _grabCamera();
  wireAttachmentUI();
  wireCameraUI();
  wireDragDrop();
  wireMic();
} /* end initComposer */
var pendingFiles = [];
export function getPendingFiles() { return pendingFiles; }
export function clearPendingFiles() { pendingFiles = []; }
function addChip(file) {
  if (file.type && file.type.indexOf("image/") === 0) {
    file._preview = URL.createObjectURL(file);
  }
  var chip = document.createElement("div");
  chip.className = "chip";
  if (file._preview) {
    var im = document.createElement("img");
    im.src = file._preview;
    chip.appendChild(im);
  } else {
    var ex = (file.name.split(".").pop() || "").toLowerCase();
    var badge = document.createElement("span");
    badge.className = "ext";
    badge.textContent = ex.slice(0, 4).toUpperCase() || "FILE";
    chip.appendChild(badge);
  }
  var n = document.createElement("span");
  n.className = "name";
  n.textContent = file.name;
  n.title = file.name;
  var s = document.createElement("span");
  s.className = "size";
  s.textContent = fmtSize(file.size);
  var x = document.createElement("button");
  x.className = "chip-x";
  x.textContent = "✕";
  x.title = "Remove";
  x.addEventListener("click", function () {
    if (file._preview) URL.revokeObjectURL(file._preview);
    pendingFiles = pendingFiles.filter(function (p) { return p !== file; });
    chip.remove();
  });
  chip.appendChild(n);
  chip.appendChild(s);
  chip.appendChild(x);
  attachments.appendChild(chip);
  pendingFiles.push(file);
}
function addFiles(list) { for (var i = 0; i < list.length; i++) addChip(list[i]); }
function closeAttachMenu() { attachMenu.classList.remove("open"); }
function wireAttachmentUI() {
$("attachBtn").addEventListener("click", function (e) {
  e.stopPropagation();
  attachMenu.classList.toggle("open");
});
document.addEventListener("click", function (e) {
  if (!attachWrap.contains(e.target)) closeAttachMenu();
});
attachMenu.querySelectorAll("button").forEach(function (opt) {
  opt.addEventListener("click", function () {
    closeAttachMenu();
    var k = opt.getAttribute("data-attach");
    if (k === "camera") openCamera();
    if (k === "photos") photoInput.click();
    if (k === "files") docInput.click();
  });
});
photoInput.addEventListener("change", function () { addFiles(photoInput.files); photoInput.value = ""; });
docInput.addEventListener("change", function () { addFiles(docInput.files); docInput.value = ""; });
} /* end wireAttachmentUI */

/* ---------- camera ---------- */
var camModal = null, camVideo = null, camCanvas = null,
  camError = null, camShot = null, camRetake = null,
  camUse = null, camCancel = null, camStream = null, shotTaken = false;
function _grabCamera() {
  camModal = $("camModal"); camVideo = $("camVideo"); camCanvas = $("camCanvas");
  camError = $("camError"); camShot = $("camShot"); camRetake = $("camRetake");
  camUse = $("camUse"); camCancel = $("camCancel");
}
function openCamera() {
  camModal.classList.remove("hidden");
  camError.classList.add("hidden");
  camCanvas.classList.add("hidden");
  camVideo.classList.remove("hidden");
  camRetake.classList.add("hidden");
  camUse.classList.add("hidden");
  camShot.classList.remove("hidden");
  camShot.disabled = false;
  shotTaken = false;
  setTimeout(function () { if (!camShot.disabled) camShot.focus(); }, 60);
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    camVideo.classList.add("hidden");
    camShot.disabled = true;
    camError.textContent = "Camera is not supported in this browser.";
    camError.classList.remove("hidden");
    return;
  }
  navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false })
    .then(function (st) { camStream = st; camVideo.srcObject = st; })
    .catch(function () {
      camStream = null;
      camVideo.classList.add("hidden");
      camShot.disabled = true;
      camError.textContent = "Camera unavailable — permission denied or no device found.";
      camError.classList.remove("hidden");
    });
}
function stopCamera() {
  if (camStream) { var t = camStream.getTracks(); for (var i = 0; i < t.length; i++) t[i].stop(); }
  camStream = null;
  camVideo.srcObject = null;
}
function closeCamera() { stopCamera(); camModal.classList.add("hidden"); }
function wireCameraUI() {
camShot.addEventListener("click", function () {
  if (!camStream) return;
  var w = camVideo.videoWidth, h = camVideo.videoHeight;
  if (!w || !h) return;
  camCanvas.width = w;
  camCanvas.height = h;
  camCanvas.getContext("2d").drawImage(camVideo, 0, 0, w, h);
  shotTaken = true;
  camCanvas.classList.remove("hidden");
  camVideo.classList.add("hidden");
  camShot.classList.add("hidden");
  camRetake.classList.remove("hidden");
  camUse.classList.remove("hidden");
});
camRetake.addEventListener("click", function () {
  shotTaken = false;
  camCanvas.classList.add("hidden");
  camVideo.classList.remove("hidden");
  camRetake.classList.add("hidden");
  camUse.classList.add("hidden");
  camShot.classList.remove("hidden");
});
camUse.addEventListener("click", function () {
  if (!shotTaken) return;
  camCanvas.toBlob(function (blob) {
    if (blob) addFiles([new File([blob], "photo-" + Date.now() + ".png", { type: "image/png" })]);
    closeCamera();
    toast("Photo attached");
  }, "image/png");
});
camCancel.addEventListener("click", closeCamera);
camModal.addEventListener("click", function (e) { if (e.target === camModal) closeCamera(); });
} /* end wireCameraUI */
function wireDragDrop() {

/* ---------- drag & drop ---------- */
var dragDepth = 0;
composer.addEventListener("dragenter", function (e) { e.preventDefault(); dragDepth++; composer.classList.add("dragover"); });
composer.addEventListener("dragover", function (e) { e.preventDefault(); });
composer.addEventListener("dragleave", function () { dragDepth--; if (dragDepth <= 0) { dragDepth = 0; composer.classList.remove("dragover"); } });
composer.addEventListener("drop", function (e) {
  e.preventDefault();
  dragDepth = 0;
  composer.classList.remove("dragover");
  addFiles(e.dataTransfer.files);
  toast("Attached");
});
} /* end wireDragDrop */

/* ---------- mic ---------- */
function wireMic() {

/* ---------- mic ---------- */
$("micBtn").addEventListener("click", function () {
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast("Voice input not supported here"); return; }
  try {
    var r = new SR();
    $("micBtn").classList.add("active");
    toast("Listening…");
    r.onresult = function (e) { input.value += e.results[0][0].transcript; input.focus(); };
    r.onend = function () { $("micBtn").classList.remove("active"); };
    r.onerror = function () { toast("Mic error or denied"); };
    r.start();
  } catch (e) { toast("Mic unavailable"); }
});
} /* end wireMic */

export { initComposer, addChip, addFiles, closeAttachMenu, openCamera, stopCamera, closeCamera, camModal };

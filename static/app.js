const state = {
  analysis: null,
  filteredTracks: [],
  selectedTrackId: "",
  trackFilter: "all",
  previewView: "table",
};

const form = document.querySelector("#analyze-form");
const analyzeButton = document.querySelector("#analyze-button");
const statusEl = document.querySelector("#status");
const dashboard = document.querySelector("#dashboard");
const thumbnailEl = document.querySelector("#video-thumbnail");
const titleEl = document.querySelector("#video-title");
const authorEl = document.querySelector("#video-author");
const lengthEl = document.querySelector("#video-length");
const trackSummary = document.querySelector("#track-summary");
const trackSearch = document.querySelector("#track-search");
const trackList = document.querySelector("#track-list");
const trackSelect = document.querySelector("#track-select");
const languageSelect = document.querySelector("#language-select");
const formatSelect = document.querySelector("#format-select");
const previewButton = document.querySelector("#preview-button");
const downloadButton = document.querySelector("#download-button");
const previewTitle = document.querySelector("#preview-title");
const previewTable = document.querySelector("#preview-table");
const previewContent = document.querySelector("#preview-content");
const filterButtons = Array.from(document.querySelectorAll(".chip"));
const presetButtons = Array.from(document.querySelectorAll(".preset"));
const tabButtons = Array.from(document.querySelectorAll(".tab"));
const tableView = document.querySelector("#table-view");
const readingView = document.querySelector("#reading-view");

function setStatus(message, tone = "idle") {
  statusEl.textContent = message;
  statusEl.className = `status ${tone}`;
}

function secondsToDuration(seconds) {
  const total = Number(seconds || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = Math.floor(total % 60);
  return [hours, minutes, secs]
    .map((value, index) => (index === 0 ? String(value) : String(value).padStart(2, "0")))
    .join(":");
}

function currentTrack() {
  if (!state.analysis) return null;
  return state.analysis.tracks.find((track) => track.track_id === state.selectedTrackId) || null;
}

function selectedLanguageCode() {
  return languageSelect.value || "";
}

function updateTabState(view) {
  state.previewView = view;
  tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  tableView.classList.toggle("hidden", view !== "table");
  readingView.classList.toggle("hidden", view !== "reading");
}

function buildDownloadUrl(download = false) {
  const track = currentTrack();
  if (!track || !state.analysis) return null;

  const params = new URLSearchParams({
    video_id: state.analysis.video_id,
    track_id: track.track_id,
    format: formatSelect.value,
    title: state.analysis.title,
    download: download ? "1" : "0",
  });

  const tlang = selectedLanguageCode();
  if (tlang && tlang !== track.language_code) {
    params.set("tlang", tlang);
  }

  return `/api/captions?${params.toString()}`;
}

function buildPreviewUrl() {
  const track = currentTrack();
  if (!track || !state.analysis) return null;

  const params = new URLSearchParams({
    video_id: state.analysis.video_id,
    track_id: track.track_id,
  });

  const tlang = selectedLanguageCode();
  if (tlang && tlang !== track.language_code) {
    params.set("tlang", tlang);
  }

  return `/api/preview?${params.toString()}`;
}

function fillTrackSelect(tracks) {
  trackSelect.innerHTML = tracks
    .map(
      (track) =>
        `<option value="${track.track_id}">${track.language_name} (${track.language_code})${
          track.is_asr ? " • auto" : ""
        }</option>`
    )
    .join("");

  if (!state.selectedTrackId && tracks.length) {
    state.selectedTrackId = tracks[0].track_id;
  }
  trackSelect.value = state.selectedTrackId;
}

function fillLanguageSelect() {
  const track = currentTrack();
  if (!track) return;

  const languages = [
    {
      language_code: track.language_code,
      language_name: `${track.language_name} (original)`,
    },
  ];

  if (track.can_translate) {
    track.translation_languages.forEach((language) => {
      if (language.language_code !== track.language_code) {
        languages.push(language);
      }
    });
  }

  languageSelect.innerHTML = languages
    .map(
      (language) =>
        `<option value="${language.language_code}">${language.language_name} (${language.language_code})</option>`
    )
    .join("");
}

function createTrackCard(track) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = `track-card ${track.track_id === state.selectedTrackId ? "selected" : ""}`;
  card.dataset.trackId = track.track_id;
  card.innerHTML = `
    <div class="track-top">
      <div>
        <h3>${track.language_name}</h3>
        <div class="track-meta">${track.language_code}</div>
      </div>
      <strong>${track.is_asr ? "AUTO" : "MANUAL"}</strong>
    </div>
    <div class="track-tags">
      <span>${track.can_translate ? "Translatable" : "Original only"}</span>
      <span>${track.is_asr ? "Auto-generated" : "Human-made"}</span>
      <span>${track.translation_languages.length} targets</span>
    </div>
  `;
  card.addEventListener("click", () => {
    state.selectedTrackId = track.track_id;
    trackSelect.value = track.track_id;
    fillLanguageSelect();
    renderTracks();
  });
  return card;
}

function trackMatchesFilter(track) {
  if (state.trackFilter === "manual" && track.is_asr) return false;
  if (state.trackFilter === "auto" && !track.is_asr) return false;
  if (state.trackFilter === "translatable" && !track.can_translate) return false;

  const query = trackSearch.value.trim().toLowerCase();
  if (!query) return true;

  const searchable = `${track.language_name} ${track.language_code} ${
    track.is_asr ? "auto generated" : "manual"
  } ${track.can_translate ? "translatable" : "original"}`.toLowerCase();

  return searchable.includes(query);
}

function renderTracks() {
  if (!state.analysis) return;

  state.filteredTracks = state.analysis.tracks.filter(trackMatchesFilter);
  trackList.innerHTML = "";

  if (!state.filteredTracks.some((track) => track.track_id === state.selectedTrackId) && state.filteredTracks.length) {
    state.selectedTrackId = state.filteredTracks[0].track_id;
    trackSelect.value = state.selectedTrackId;
    fillLanguageSelect();
  }

  if (!state.filteredTracks.length) {
    trackList.innerHTML = `<div class="empty-state">No tracks match the current filters.</div>`;
    return;
  }

  state.filteredTracks.forEach((track) => trackList.appendChild(createTrackCard(track)));
}

function renderPreview(rows, plainText) {
  previewTable.innerHTML = rows
    .map(
      (row) => `
        <div class="preview-table-row">
          <span>${row.index}</span>
          <span>${row.start}</span>
          <span>${row.end}</span>
          <span class="preview-text">${row.text}</span>
        </div>
      `
    )
    .join("");
  previewContent.textContent = plainText;
}

function renderAnalysis(analysis) {
  state.analysis = analysis;
  state.selectedTrackId = analysis.tracks[0]?.track_id || "";

  thumbnailEl.src = analysis.thumbnail;
  titleEl.textContent = analysis.title;
  authorEl.textContent = analysis.author;
  lengthEl.textContent = `Duration ${secondsToDuration(analysis.length_seconds)}`;
  trackSummary.textContent = `${analysis.tracks.length} subtitle track${analysis.tracks.length === 1 ? "" : "s"}`;

  fillTrackSelect(analysis.tracks);
  fillLanguageSelect();
  renderTracks();
  dashboard.classList.remove("hidden");
  previewTitle.textContent = "Transcript preview";
  previewTable.innerHTML = `<div class="empty-state">Choose a track and refresh the preview.</div>`;
  previewContent.textContent = "Choose a track and refresh the preview.";
}

async function analyzeVideo(event) {
  event.preventDefault();
  const formData = new FormData(form);
  const url = String(formData.get("url") || "").trim();
  if (!url) {
    setStatus("Enter a YouTube URL to continue.", "error");
    return;
  }

  analyzeButton.disabled = true;
  setStatus("Inspecting YouTube subtitle tracks...", "idle");

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Could not analyze that video.");
    }
    renderAnalysis(payload.data);
    setStatus("Tracks loaded. Pick a subtitle source and preview it.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    analyzeButton.disabled = false;
  }
}

async function previewCaptions() {
  const url = buildPreviewUrl();
  if (!url) {
    setStatus("Analyze a video before previewing subtitles.", "error");
    return;
  }

  previewButton.disabled = true;
  setStatus("Loading subtitle preview...", "idle");

  try {
    const response = await fetch(url);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Could not load the subtitle preview.");
    }
    const track = currentTrack();
    const languageLabel = languageSelect.options[languageSelect.selectedIndex]?.textContent || "";
    previewTitle.textContent = `${track.language_name} -> ${languageLabel}`;
    renderPreview(payload.data.rows, payload.data.plain_text);
    setStatus("Preview updated.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    previewButton.disabled = false;
  }
}

function downloadCaptions() {
  const url = buildDownloadUrl(true);
  if (!url) {
    setStatus("Analyze a video before downloading subtitles.", "error");
    return;
  }
  window.open(url, "_blank", "noopener");
  setStatus("Download started in a new tab.", "success");
}

trackSearch.addEventListener("input", renderTracks);

filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.trackFilter = button.dataset.filter;
    filterButtons.forEach((item) => item.classList.toggle("active", item === button));
    renderTracks();
  });
});

trackSelect.addEventListener("change", () => {
  state.selectedTrackId = trackSelect.value;
  fillLanguageSelect();
  renderTracks();
});

presetButtons.forEach((button) => {
  button.addEventListener("click", () => {
    formatSelect.value = button.dataset.format;
  });
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => updateTabState(button.dataset.view));
});

form.addEventListener("submit", analyzeVideo);
previewButton.addEventListener("click", previewCaptions);
downloadButton.addEventListener("click", downloadCaptions);
updateTabState("table");

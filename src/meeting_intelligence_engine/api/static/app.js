const state = {
  meetings: [],
  selectedMeetingId: null,
  pollTimer: null,
};

const el = {
  uploadForm: document.getElementById("uploadForm"),
  fileInput: document.getElementById("fileInput"),
  titleInput: document.getElementById("titleInput"),
  uploadStatus: document.getElementById("uploadStatus"),
  refreshButton: document.getElementById("refreshButton"),
  meetingCount: document.getElementById("meetingCount"),
  meetingList: document.getElementById("meetingList"),
  meetingTitle: document.getElementById("meetingTitle"),
  meetingMeta: document.getElementById("meetingMeta"),
  detailEmpty: document.getElementById("detailEmpty"),
  detailContent: document.getElementById("detailContent"),
  deleteButton: document.getElementById("deleteButton"),
  statusValue: document.getElementById("statusValue"),
  stageValue: document.getElementById("stageValue"),
  progressValue: document.getElementById("progressValue"),
  durationValue: document.getElementById("durationValue"),
  progressBar: document.getElementById("progressBar"),
  transcriptText: document.getElementById("transcriptText"),
  actionItems: document.getElementById("actionItems"),
  decisions: document.getElementById("decisions"),
  topics: document.getElementById("topics"),
  actionCount: document.getElementById("actionCount"),
  decisionCount: document.getElementById("decisionCount"),
  topicCount: document.getElementById("topicCount"),
  artifactTxt: document.getElementById("artifactTxt"),
  artifactSrt: document.getElementById("artifactSrt"),
  artifactJson: document.getElementById("artifactJson"),
  artifactMd: document.getElementById("artifactMd"),
  queryForm: document.getElementById("queryForm"),
  queryInput: document.getElementById("queryInput"),
  scopeMeetingOnly: document.getElementById("scopeMeetingOnly"),
  queryAnswer: document.getElementById("queryAnswer"),
  querySources: document.getElementById("querySources"),
};

function formatSeconds(value) {
  if (value == null || Number.isNaN(value)) return "-";
  const total = Math.round(Number(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatRange(start, end) {
  const left = formatSeconds(start);
  const right = formatSeconds(end);
  if (left === "-" && right === "-") return "-";
  if (right === "-") return left;
  if (left === "-") return right;
  return `${left} - ${right}`;
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(payload || response.statusText);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function setActiveTab(tabName) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === tabName);
  });
}

function renderMeetings() {
  el.meetingCount.textContent = String(state.meetings.length);
  if (!state.meetings.length) {
    el.meetingList.innerHTML = '<div class="empty-state">No meetings yet.</div>';
    return;
  }
  el.meetingList.innerHTML = state.meetings
    .map(
      (meeting) => `
        <button class="meeting-item ${meeting.id === state.selectedMeetingId ? "active" : ""}" type="button" data-id="${meeting.id}">
          <h3>${escapeHtml(meeting.title)}</h3>
          <div class="meta">
            <span>${escapeHtml(meeting.status)} · ${escapeHtml(meeting.processing_stage)}</span>
            <span>${formatSeconds(meeting.duration_seconds)}</span>
            <span>${formatDate(meeting.created_at)}</span>
          </div>
        </button>
      `,
    )
    .join("");
  el.meetingList.querySelectorAll("[data-id]").forEach((button) => {
    button.addEventListener("click", () => {
      selectMeeting(button.dataset.id);
    });
  });
}

function renderDetailShell(meeting) {
  if (!meeting) {
    el.detailEmpty.classList.remove("hidden");
    el.detailContent.classList.add("hidden");
    el.deleteButton.disabled = true;
    el.meetingTitle.textContent = "Select a meeting";
    el.meetingMeta.textContent = "Nothing selected.";
    return;
  }
  el.detailEmpty.classList.add("hidden");
  el.detailContent.classList.remove("hidden");
  el.deleteButton.disabled = false;
  el.meetingTitle.textContent = meeting.title;
  el.meetingMeta.textContent = `${meeting.id} · created ${formatDate(meeting.created_at)}`;
  el.statusValue.textContent = meeting.status;
  el.stageValue.textContent = meeting.processing_stage;
  el.progressValue.textContent = `${Math.round(meeting.progress_percent || 0)}%`;
  el.durationValue.textContent = formatSeconds(meeting.duration_seconds);
  el.progressBar.style.width = `${meeting.progress_percent || 0}%`;
  const base = `/meetings/${meeting.id}/artifacts`;
  el.artifactTxt.href = `${base}/txt`;
  el.artifactSrt.href = `${base}/srt`;
  el.artifactJson.href = `${base}/json`;
  el.artifactMd.href = `${base}/md`;
}

function renderListItems(target, items, formatter, emptyText) {
  if (!items.length) {
    target.innerHTML = `<div class="empty-state">${emptyText}</div>`;
    return;
  }
  target.innerHTML = items.map(formatter).join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadMeetings() {
  state.meetings = await api("/meetings");
  renderMeetings();
  if (!state.selectedMeetingId && state.meetings.length) {
    await selectMeeting(state.meetings[0].id);
  } else if (state.selectedMeetingId) {
    const stillExists = state.meetings.find((item) => item.id === state.selectedMeetingId);
    if (stillExists) {
      renderMeetings();
    } else {
      state.selectedMeetingId = null;
      renderDetailShell(null);
    }
  }
}

async function selectMeeting(meetingId) {
  state.selectedMeetingId = meetingId;
  renderMeetings();
  await refreshSelectedMeeting();
}

async function refreshSelectedMeeting() {
  if (!state.selectedMeetingId) return;
  const meeting = await api(`/meetings/${state.selectedMeetingId}`);
  renderDetailShell(meeting);
  await Promise.allSettled([loadTranscript(meeting.id), loadAnalytics(meeting.id)]);
  startPollingIfNeeded(meeting);
}

async function loadTranscript(meetingId) {
  try {
    const transcript = await api(`/meetings/${meetingId}/transcript`);
    el.transcriptText.textContent = transcript.segments
      .map(
        (segment) =>
          `[${formatRange(segment.start_time, segment.end_time)}] ${segment.display_speaker || segment.speaker_name || segment.speaker_id}: ${segment.text}`,
      )
      .join("\n\n");
  } catch (_error) {
    el.transcriptText.textContent = "Transcript not ready.";
  }
}

async function loadAnalytics(meetingId) {
  const [actionItems, decisions, topics] = await Promise.all([
    api(`/meetings/${meetingId}/action-items`).catch(() => []),
    api(`/meetings/${meetingId}/decisions`).catch(() => []),
    api(`/meetings/${meetingId}/topics`).catch(() => []),
  ]);

  el.actionCount.textContent = String(actionItems.length);
  el.decisionCount.textContent = String(decisions.length);
  el.topicCount.textContent = String(topics.length);

  renderListItems(
    el.actionItems,
    actionItems,
    (item) => `
      <article class="item">
        <h4>${escapeHtml(item.description)}</h4>
        <p>${escapeHtml(item.assignee_inferred || "Unassigned")} · ${escapeHtml(item.priority)} · confidence ${Number(item.confidence || 0).toFixed(2)}</p>
        <p class="tagline">${item.timestamp != null ? `at ${formatSeconds(item.timestamp)}` : "no timestamp"}${item.deadline ? ` · due ${escapeHtml(item.deadline)}` : ""}</p>
      </article>
    `,
    "No action items.",
  );
  renderListItems(
    el.decisions,
    decisions,
    (item) => `
      <article class="item">
        <h4>${escapeHtml(item.decision_text)}</h4>
        <p>${escapeHtml(item.context || "No transcript context available.")}</p>
        <p class="tagline">${item.timestamp != null ? `at ${formatSeconds(item.timestamp)}` : "no timestamp"} · stakeholders ${escapeHtml((item.stakeholders || []).join(", ") || "-")}</p>
      </article>
    `,
    "No decisions.",
  );
  renderListItems(
    el.topics,
    topics,
    (item) => `
      <article class="item">
        <h4>${escapeHtml(item.topic_name)}</h4>
        <p>${formatRange(item.start_time, item.end_time)}</p>
        <p class="tagline">${escapeHtml((item.keywords || []).join(", ") || "No keywords")} · confidence ${Number(item.confidence || 0).toFixed(2)}</p>
      </article>
    `,
    "No topics.",
  );
}

function startPollingIfNeeded(meeting) {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
  if (!meeting || !["pending", "processing"].includes(meeting.status)) {
    return;
  }
  state.pollTimer = setTimeout(() => {
    refreshSelectedMeeting().catch((error) => {
      console.error(error);
    });
  }, 4000);
}

async function handleUpload(event) {
  event.preventDefault();
  const file = el.fileInput.files?.[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  if (el.titleInput.value.trim()) {
    body.append("title", el.titleInput.value.trim());
  }
  el.uploadStatus.textContent = "Uploading...";
  try {
    const result = await api("/meetings/upload", { method: "POST", body });
    el.uploadStatus.textContent = `Queued ${result.meeting_id}`;
    el.uploadForm.reset();
    await loadMeetings();
    await selectMeeting(result.meeting_id);
  } catch (error) {
    el.uploadStatus.textContent = error.message;
  }
}

async function handleDelete() {
  if (!state.selectedMeetingId) return;
  const confirmed = window.confirm("Delete this meeting and its local files?");
  if (!confirmed) return;
  await api(`/meetings/${state.selectedMeetingId}`, { method: "DELETE" });
  state.selectedMeetingId = null;
  renderDetailShell(null);
  await loadMeetings();
}

async function handleQuery(event) {
  event.preventDefault();
  const query = el.queryInput.value.trim();
  if (!query) return;
  const scoped = el.scopeMeetingOnly.checked && state.selectedMeetingId;
  const path = scoped ? `/meetings/${state.selectedMeetingId}/query` : "/query";
  el.queryAnswer.textContent = "Running query...";
  el.querySources.innerHTML = "";
  try {
    const result = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k: 5 }),
    });
    el.queryAnswer.textContent = result.answer || "No answer returned.";
    renderListItems(
      el.querySources,
      result.sources || [],
      (source) => `
        <article class="item">
          <h4>${escapeHtml(source.meeting_title || source.meeting_id || source.source || "Source")}</h4>
          <p>${escapeHtml((source.speakers || []).join(", ") || "No speaker metadata")}</p>
          <p class="tagline">${formatRange(source.start_time, source.end_time)} · score ${Number(source.score || 0).toFixed(3)}</p>
          <p class="tagline">${escapeHtml(source.content || "")}</p>
        </article>
      `,
      "No sources.",
    );
  } catch (error) {
    el.queryAnswer.textContent = error.message;
  }
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => setActiveTab(button.dataset.tab));
});

el.uploadForm.addEventListener("submit", handleUpload);
el.refreshButton.addEventListener("click", () => loadMeetings().then(refreshSelectedMeeting));
el.deleteButton.addEventListener("click", handleDelete);
el.queryForm.addEventListener("submit", handleQuery);

loadMeetings().catch((error) => {
  console.error(error);
});

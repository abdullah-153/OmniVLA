const shell = document.querySelector("#execution-shell");
const beacon = document.querySelector("#run-beacon");
const stateLabel = document.querySelector("#beacon-state");
const phaseLabel = document.querySelector("#phase-label");
const actionText = document.querySelector("#action-text");
const traceList = document.querySelector("#trace-list");
const traceCount = document.querySelector("#trace-count");
const hitlPanel = document.querySelector("#hitl-panel");
const hitlQuestion = document.querySelector("#hitl-question");
const hitlInput = document.querySelector("#hitl-input");
const hitlSubmit = document.querySelector("#hitl-submit");
const pauseButton = document.querySelector("#pause-button");
const stopButton = document.querySelector("#stop-button");
const modelLabel = document.querySelector("#model-label");
const phaseDuration = document.querySelector("#phase-duration");

let paused = false;
let requestInFlight = false;
let activePhaseName = "idle";
let phaseStartedAt = null;
let phaseTimer = null;

const WORKING_STATES = new Set(["thinking", "acting", "verifying", "hitl", "queued", "stopping", "paused"]);

const phaseCopy = {
  thinking: "Reading the current desktop context",
  acting: "Sending the selected native input",
  verifying: "Checking the screen outcome",
  hitl: "Waiting for the operator",
  paused: "Execution is paused",
  stopping: "Stopping at a safe boundary",
  done: "Run completed",
  failed: "Run needs review",
  error: "Runtime needs attention",
};

const api = (path, options = {}) =>
  fetch("http://127.0.0.1:8000" + path, { cache: "no-store", ...options });

const setInteractive = (enabled) => {
  if (window.overlayAPI) window.overlayAPI.setIgnoreMouseEvents(!enabled, !enabled);
};

const toTitleCase = (value) =>
  String(value || "idle")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const activePhase = (data) => (data.paused ? "paused" : data.phase || data.status || "idle");

const formatElapsed = (seconds) => {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  if (value < 60) return String(value) + "s";
  return String(Math.floor(value / 60)) + "m " + String(value % 60).padStart(2, "0") + "s";
};

const updatePhaseDuration = () => {
  const active = WORKING_STATES.has(activePhaseName);
  if (!active || !phaseStartedAt) {
    phaseDuration.textContent = activePhaseName === "done" ? "Complete" : "Standing by";
    return;
  }
  phaseDuration.textContent = formatElapsed(Date.now() / 1000 - phaseStartedAt);
};

const syncPhaseClock = (phase, startedAt, active) => {
  const parsedStart = Number(startedAt);
  const normalizedStart = Number.isFinite(parsedStart) && parsedStart > 0 ? parsedStart : null;
  if (phase !== activePhaseName || (normalizedStart !== null && normalizedStart !== phaseStartedAt)) {
    activePhaseName = phase;
    phaseStartedAt = normalizedStart ?? Date.now() / 1000;
  }
  if (active && !phaseTimer) phaseTimer = window.setInterval(updatePhaseDuration, 250);
  if (!active && phaseTimer) {
    window.clearInterval(phaseTimer);
    phaseTimer = null;
  }
  updatePhaseDuration();
};

const appendTrace = (label, current = false) => {
  const item = document.createElement("li");
  if (current) item.classList.add("is-current");
  const text = document.createElement("span");
  text.textContent = label;
  item.append(text);
  traceList.append(item);
};

const renderTrace = (data, phase) => {
  traceList.replaceChildren();
  const steps = Array.isArray(data.steps) ? data.steps.slice(-3) : [];
  const knownActions = steps
    .map((step) => String(step.action || "").trim())
    .filter(Boolean);
  knownActions.forEach((action) => appendTrace(action));

  if (WORKING_STATES.has(phase)) {
    appendTrace(data.current_action || phaseCopy[phase] || "Working locally", true);
  }
  if (!traceList.children.length) appendTrace("Waiting for the first observed action");

  const completed = Array.isArray(data.steps) ? data.steps.length : 0;
  traceCount.textContent = completed ? String(completed) + " recorded" : "No actions yet";
};

const renderStatus = (data) => {
  const phase = activePhase(data);
  const active = WORKING_STATES.has(phase) || WORKING_STATES.has(data.status);

  shell.classList.toggle("is-visible", active);
  shell.dataset.tone = phase;
  syncPhaseClock(phase, data.phase_started_at, active);
  paused = Boolean(data.paused);
  stateLabel.textContent = toTitleCase(phase);
  phaseLabel.textContent = phaseCopy[phase] || "Preparing local execution";
  actionText.textContent = data.current_action || "Working on the reviewed runbook.";
  const lastCycle = Number(data.timing?.last_step_ms);
  const cycleCopy = Number.isFinite(lastCycle) && lastCycle > 0 ? " / " + formatElapsed(lastCycle / 1000) + " cycle" : " / local control";
  modelLabel.textContent = (data.settings?.model_type || "local").toUpperCase() + cycleCopy;
  pauseButton.textContent = paused ? "Resume" : "Pause";

  renderTrace(data, phase);

  const needsHitl = phase === "hitl" || data.status === "hitl";
  hitlPanel.hidden = !needsHitl;
  if (needsHitl) {
    hitlQuestion.textContent = data.current_action || "Human input is required.";
    setInteractive(true);
    if (document.activeElement !== hitlInput) hitlInput.focus();
  } else if (!active) {
    setInteractive(false);
  }
};

const submitHitl = () => {
  const response = hitlInput.value.trim();
  if (!response) return;
  api("/api/hitl_submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ response }),
  })
    .then(() => {
      hitlInput.value = "";
      setInteractive(false);
    })
    .catch(() => undefined);
};

beacon.addEventListener("mouseenter", () => setInteractive(true));
beacon.addEventListener("mouseleave", () => {
  if (!hitlPanel.hidden) return;
  setInteractive(false);
});

pauseButton.addEventListener("click", () => {
  api(paused ? "/api/resume" : "/api/pause", { method: "POST", body: "{}" }).catch(() => undefined);
});

stopButton.addEventListener("click", () => {
  api("/api/stop", { method: "POST", body: "{}" }).catch(() => undefined);
});

hitlSubmit.addEventListener("click", submitHitl);
hitlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitHitl();
  }
});

const pollStatus = async () => {
  if (!requestInFlight) {
    requestInFlight = true;
    try {
      const response = await api("/api/status");
      if (response.ok) renderStatus(await response.json());
    } catch {
      // The overlay simply stays quiet while the local command center restarts.
    } finally {
      requestInFlight = false;
    }
  }
  window.setTimeout(pollStatus, shell.classList.contains("is-visible") ? 450 : 900);
};

setInteractive(false);
pollStatus();

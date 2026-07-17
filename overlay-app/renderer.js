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

let paused = false;
let requestInFlight = false;

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
  paused = Boolean(data.paused);
  stateLabel.textContent = toTitleCase(phase);
  phaseLabel.textContent = phaseCopy[phase] || "Preparing local execution";
  actionText.textContent = data.current_action || "Working on the reviewed runbook.";
  modelLabel.textContent = (data.settings?.model_type || "local").toUpperCase() + " / local control";
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

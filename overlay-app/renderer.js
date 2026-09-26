const shell = document.querySelector("#execution-shell");
const beacon = document.querySelector("#run-beacon");
const beaconToggle = document.querySelector("#beacon-toggle");
const actionText = document.querySelector("#action-text");
const capsuleActionText = document.querySelector("#capsule-action-text");
const traceList = document.querySelector("#trace-list");

const traceCount = document.querySelector("#trace-count");
const hitlPanel = document.querySelector("#hitl-panel");
const hitlQuestion = document.querySelector("#hitl-question");
const hitlInput = document.querySelector("#hitl-input");
const hitlSubmit = document.querySelector("#hitl-submit");
const pauseButton = document.querySelector("#pause-button");
const stopButton = document.querySelector("#stop-button");
const closeButton = document.querySelector("#beacon-close-btn");
const phaseDuration = document.querySelector("#phase-duration");



let paused = false;
let requestInFlight = false;
let activePhaseName = "idle";
let phaseStartedAt = null;
let phaseTimer = null;

const WORKING_STATES = new Set(["thinking", "acting", "verifying", "hitl", "queued", "stopping", "paused"]);

const phaseCopy = {
  thinking: "Reading the screen",
  acting: "Taking the next action",
  verifying: "Checking the result",
  hitl: "Input needed",
  paused: "Paused",
  stopping: "Stopping",
  done: "Completed",
  failed: "Needs attention",
  error: "Needs attention",
};

let sessionToken = "";
let intervention = null;
const api = async (path, options = {}) => {
  if (!sessionToken) {
    const session = await fetch("/api/session", { cache: "no-store" });
    if (!session.ok) throw new Error("Desktop session unavailable");
    sessionToken = (await session.json()).token;
  }
  const headers = new Headers(options.headers || {});
  headers.set("X-OmniVLA-Session", sessionToken);
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers,
  });
  if (response.status === 401) sessionToken = "";
  if (!response.ok) throw new Error((await response.json()).error || "Request failed");
  return response;
};

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
    .map((step) => String(step.action_text || step.output || "Action completed").trim())
    .filter(Boolean);
  knownActions.forEach((action) => appendTrace(action));

  if (WORKING_STATES.has(phase)) {
    appendTrace(data.current_action || phaseCopy[phase] || "Working locally", true);
  }
  if (!traceList.children.length) appendTrace("Waiting for the first action");

  const completed = Array.isArray(data.steps) ? data.steps.length : 0;
  traceCount.textContent = completed ? String(completed) + " recorded" : "No actions yet";
};

const renderStatus = (data) => {
  const phase = activePhase(data);
  const active = WORKING_STATES.has(phase) || WORKING_STATES.has(data.status);

  const previousPhase = shell.dataset.tone;
  shell.classList.toggle("is-visible", active);
  shell.dataset.tone = phase;
  if (active && previousPhase !== phase) {
    shell.classList.remove("phase-shift");
    void shell.offsetWidth;
    shell.classList.add("phase-shift");
    window.setTimeout(() => shell.classList.remove("phase-shift"), 500);
  }
  if (!active) {
    beacon.classList.remove("is-expanded");
    beaconToggle.setAttribute("aria-expanded", "false");
  }
  syncPhaseClock(phase, data.phase_started_at, active);
  paused = Boolean(data.paused);
  actionText.textContent = data.current_action || phaseCopy[phase] || "Working";
  if (capsuleActionText) capsuleActionText.textContent = data.current_action || phaseCopy[phase] || "Working";
  pauseButton.textContent = paused ? "Resume" : "Pause";

  renderTrace(data, phase);


  intervention = data.intervention || null;
  const needsHitl = Boolean(intervention);
  hitlPanel.dataset.requestId = intervention?.id || "";
  const approval = ["approval", "completion"].includes(intervention?.kind);
  document.getElementById("hitl-approve").hidden = !approval;
  document.getElementById("hitl-deny").hidden = !needsHitl;
  hitlInput.hidden = approval;
  hitlSubmit.hidden = approval;
  hitlInput.type = intervention?.kind === "secret" ? "password" : "text";
  hitlPanel.hidden = !needsHitl;
  if (needsHitl) {
    hitlQuestion.textContent = intervention.question;
    setInteractive(true);
    if (!approval && document.activeElement !== hitlInput) hitlInput.focus();
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
    body: JSON.stringify({ ...intervention, response }),
  })
    .then(() => {
      hitlInput.value = "";
      setInteractive(false);
    })
    .catch(error => { hitlQuestion.textContent = error.message; });
};

beacon.addEventListener("mouseenter", () => setInteractive(true));
beacon.addEventListener("mouseleave", () => {
  if (!hitlPanel.hidden) return;
  beacon.classList.remove("is-expanded");
  beaconToggle.setAttribute("aria-expanded", "false");
  setInteractive(false);
});

beaconToggle.addEventListener("click", () => {
  const expanded = beacon.classList.toggle("is-expanded");
  beaconToggle.setAttribute("aria-expanded", String(expanded));
});

pauseButton.addEventListener("click", () => {
  api(paused ? "/api/resume" : "/api/pause", { method: "POST", body: "{}" }).catch(() => undefined);
});

stopButton.addEventListener("click", () => {
  api("/api/stop", { method: "POST", body: "{}" }).catch(() => undefined);
});

if (closeButton) {
  closeButton.addEventListener("click", (e) => {
    e.stopPropagation();
    if (confirm("Quit OmniVLA and stop the current task?")) {
      api("/api/shutdown", { method: "POST", body: "{}" }).catch(() => undefined);
      window.close();
    }
  });
}


document.getElementById("hitl-approve").addEventListener("click", () => { hitlInput.value = "approve"; submitHitl(); });
document.getElementById("hitl-deny").addEventListener("click", () => { hitlInput.value = "deny"; submitHitl(); });
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
      if (response.ok) {
        const payload = await response.json();
        renderStatus(payload.execution_live || payload);
      }
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

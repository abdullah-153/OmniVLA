const DOM = {
  app: document.querySelector("#app-shell"),
  statusDot: document.querySelector("[data-status-dot]"),
  statusLabel: document.querySelector("[data-status-label]"),
  connectionBanner: document.querySelector("#connection-banner"),
  pairingForm: document.querySelector("#pairing-form"),
  pairingCode: document.querySelector("#pairing-code"),
  taskInput: document.querySelector("#task-input"),
  draftPlan: document.querySelector("#draft-plan"),
  planContent: document.querySelector("#plan-content"),
  planFooter: document.querySelector("#plan-footer"),
  planState: document.querySelector("#plan-state"),
  riskSummary: document.querySelector("#risk-summary"),
  approvePlan: document.querySelector("#approve-plan"),
  metricStatus: document.querySelector("#metric-status"),
  metricStep: document.querySelector("#metric-step"),
  metricLatency: document.querySelector("#metric-latency"),
  metricModel: document.querySelector("#metric-model"),
  livePulse: document.querySelector("#live-pulse"),
  activeAction: document.querySelector("#active-action"),
  pauseButton: document.querySelector("#pause-button"),
  retryButton: document.querySelector("#retry-button"),
  stopButton: document.querySelector("#stop-button"),
  timeline: document.querySelector("#execution-timeline"),
  conversationList: document.querySelector("#conversation-list"),
  auditList: document.querySelector("#audit-list"),
  console: document.querySelector("#console-output"),
  screenImage: document.querySelector("#screen-image"),
  screenEmpty: document.querySelector("#screen-empty"),
  canvasStatus: document.querySelector("#canvas-status"),
  intervention: document.querySelector("#intervention-section"),
  interventionQuestion: document.querySelector("#intervention-question"),
  interventionInput: document.querySelector("#intervention-input"),
  healthState: document.querySelector("#health-state"),
  healthVram: document.querySelector("#health-vram"),
  healthLayers: document.querySelector("#health-layers"),
  healthPlanner: document.querySelector("#health-planner"),
  healthCritic: document.querySelector("#health-critic"),
  policyState: document.querySelector("#policy-state"),
  requireApproval: document.querySelector("#require-approval"),
  remoteControl: document.querySelector("#remote-control"),
  savePolicy: document.querySelector("#save-policy"),
  pairingToken: document.querySelector("#pairing-token"),
  pairingState: document.querySelector("#pairing-state"),
  pairingAddress: document.querySelector("#pairing-address"),
  pairingExpiry: document.querySelector("#pairing-expiry"),
  settingsForm: document.querySelector("#settings-form"),
  settingModelType: document.querySelector("#setting-model-type"),
  settingTemperature: document.querySelector("#setting-temperature"),
  settingModelLabel: document.querySelector("#setting-model-label"),
  settingModelPath: document.querySelector("#setting-model-path"),
  settingMaxSteps: document.querySelector("#setting-max-steps"),
  settingRecording: document.querySelector("#setting-recording"),
  settingApiKey: document.querySelector("#setting-api-key"),
  approvalDialog: document.querySelector("#approval-dialog"),
  approvalCopy: document.querySelector("#approval-copy"),
  approvalRisks: document.querySelector("#approval-risks"),
  confirmApproval: document.querySelector("#confirm-approval"),
  screenDialog: document.querySelector("#screen-dialog"),
  screenDialogImage: document.querySelector("#screen-dialog-image"),
  toastRegion: document.querySelector("#toast-region"),
  installButton: document.querySelector("#install-app"),
};

const state = {
  activeView: "workbench",
  pairingToken: sessionStorage.getItem("omnivla-pairing-token") || "",
  status: null,
  activePlan: null,
  pendingApproval: null,
  installPrompt: null,
  pairingDetails: null,
  statusRequestInFlight: false,
  settingsDirty: false,
  policyDirty: false,
};

const WORKING_STATES = new Set(["thinking", "acting", "verifying", "hitl", "queued", "stopping", "paused"]);

const createElement = (tagName, options = {}) => {
  const element = document.createElement(tagName);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = options.text;
  if (options.type) element.type = options.type;
  if (options.ariaLabel) element.setAttribute("aria-label", options.ariaLabel);
  return element;
};

const toTitleCase = (value) =>
  String(value || "idle")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

const formatTime = (timestamp) => {
  if (!timestamp) return "—";
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

const formatExpiry = (seconds) => {
  if (!Number.isFinite(seconds) || seconds <= 0) return "expired";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return String(minutes) + "m " + String(remainder) + "s";
};

const formatDuration = (milliseconds) => {
  const value = Number(milliseconds);
  if (!Number.isFinite(value) || value <= 0) return "—";
  if (value < 1000) return String(Math.round(value)) + " ms";
  const seconds = value / 1000;
  return seconds < 10 ? seconds.toFixed(1) + " s" : Math.round(seconds) + " s";
};

const showToast = (message, type = "") => {
  const toast = createElement("div", {
    className: "toast " + (type ? "is-" + type : ""),
    text: message,
  });
  DOM.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
};

const setButtonBusy = (button, isBusy, busyLabel) => {
  if (!button) return;
  if (isBusy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = busyLabel;
    button.disabled = true;
    return;
  }
  if (button.dataset.originalLabel) {
    button.textContent = button.dataset.originalLabel;
    delete button.dataset.originalLabel;
  }
};

const api = async (path, options = {}) => {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (state.pairingToken) headers.set("X-OmniVLA-Pairing", state.pairingToken);

  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;

  if (!response.ok) {
    const error = new Error(payload?.error || payload?.message || "Request failed (" + String(response.status) + ").");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
};

const requireLocalControl = () => {
  if (state.status?.access?.is_local) return true;
  showToast("This policy action is available from the paired desktop only.");
  return false;
};

const showPairingPrompt = () => {
  DOM.connectionBanner.hidden = false;
  DOM.pairingCode.focus();
};

const hidePairingPrompt = () => {
  DOM.connectionBanner.hidden = true;
};

const openView = (view) => {
  if (!["workbench", "activity", "safety", "settings"].includes(view)) return;
  state.activeView = view;
  document.querySelectorAll("[data-view]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.view === view);
  });
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    const isActive = button.dataset.viewTarget === view;
    button.classList.toggle("is-active", isActive);
    if (isActive) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (view === "safety") void fetchPairingDetails();
};

const setStatusPresentation = (status, phase, paused) => {
  const normalized = paused ? "paused" : phase || status || "offline";
  const isWorking = WORKING_STATES.has(normalized) || WORKING_STATES.has(status);
  const isSafe = normalized === "done" || status === "done";
  DOM.statusDot.className = "status-dot " + (isWorking ? "is-working" : isSafe ? "is-active" : "");
  DOM.statusLabel.textContent = toTitleCase(normalized);
  DOM.metricStatus.textContent = toTitleCase(normalized);
  DOM.livePulse.classList.toggle("is-idle", !isWorking);
  DOM.livePulse.lastChild.textContent = isWorking ? " Live" : " Ready";
  DOM.app.dataset.runState = normalized;
};

const renderConversations = (chats, activeId) => {
  const fragment = document.createDocumentFragment();
  if (!Array.isArray(chats) || chats.length === 0) {
    fragment.append(createElement("p", { className: "audit-empty", text: "No saved runs yet." }));
  }

  chats
    .slice()
    .reverse()
    .forEach((chat) => {
      const item = createElement("button", {
        className: "conversation-item " + (chat.id === activeId ? "is-active" : ""),
        type: "button",
      });
      item.dataset.chatId = chat.id || "";
      const copy = createElement("span", { className: "conversation-copy" });
      copy.append(
        createElement("strong", { text: chat.title || "Untitled run" }),
        createElement("span", { text: toTitleCase(chat.status || "draft") })
      );
      const dot = createElement("span", {
        className: "conversation-state " + (chat.status === "success" ? "is-success" : ""),
      });
      item.append(copy, dot);
      fragment.append(item);
    });
  DOM.conversationList.replaceChildren(fragment);
};

const renderPlan = (activePlan, serverStatus) => {
  state.activePlan = activePlan || null;
  const isPlanning = serverStatus === "thinking" && !activePlan;
  if (isPlanning) {
    DOM.planState.textContent = "Drafting";
    DOM.planState.className = "state-label";
    DOM.planContent.replaceChildren(
      createElement("div", { className: "empty-state", text: "Planner is shaping a runbook from your intent…" })
    );
    DOM.planFooter.hidden = true;
    return;
  }

  if (!activePlan?.plan) {
    DOM.planState.textContent = "Awaiting intent";
    DOM.planState.className = "state-label";
    const empty = createElement("div", { className: "empty-state" });
    empty.append(
      createElement("span", { className: "empty-mark", text: "▲" }),
      createElement("p", {
        text: "Draft a plan to see scope, expected actions, and any safety checks before execution begins.",
      })
    );
    DOM.planContent.replaceChildren(empty);
    DOM.planFooter.hidden = true;
    return;
  }

  DOM.planState.textContent = "Ready for review";
  DOM.planState.className = "state-label is-ready";
  DOM.planContent.replaceChildren(createElement("p", { className: "plan-message", text: activePlan.plan }));
  const reasons = activePlan.risk?.reasons || [];
  DOM.riskSummary.textContent = reasons.length
    ? "Approval includes: " + reasons.join("; ") + "."
    : "No high-impact intent detected in the task brief.";
  DOM.planFooter.hidden = false;
};

const renderTimeline = (steps) => {
  if (!Array.isArray(steps) || steps.length === 0) {
    DOM.timeline.replaceChildren(
      createElement("div", { className: "timeline-empty", text: "Execution steps will appear here as the agent works." })
    );
    return;
  }

  const fragment = document.createDocumentFragment();
  steps.slice(-10).forEach((step) => {
    const row = createElement("article", { className: "timeline-event" });
    const successful = Boolean(step.success);
    const copy = createElement("div", { className: "timeline-copy" });
    copy.append(
      createElement("strong", { text: step.action || "Agent action" }),
      createElement("p", { text: step.thought || step.output || "No detail captured." })
    );
    row.append(
      createElement("span", { className: "timeline-step", text: String(step.step || "—").padStart(2, "0") }),
      copy,
      createElement("span", {
        className: "timeline-state " + (successful ? "is-success" : ""),
        text: successful ? "verified" : step.eval_state || "reviewing",
      })
    );
    fragment.append(row);
  });
  DOM.timeline.replaceChildren(fragment);
};

const renderAudit = (events) => {
  const fragment = document.createDocumentFragment();
  if (!Array.isArray(events) || events.length === 0) {
    fragment.append(createElement("li", { className: "audit-empty", text: "Control-plane events will appear here." }));
  } else {
    events
      .slice()
      .reverse()
      .slice(0, 50)
      .forEach((event) => {
        const item = createElement("li", { className: "audit-entry" });
        const copy = createElement("div");
        copy.append(
          createElement("strong", { text: event.kind || "event" }),
          createElement("p", { text: event.message || "No detail recorded." })
        );
        item.append(createElement("time", { text: formatTime(event.timestamp) }), copy);
        fragment.append(item);
      });
  }
  DOM.auditList.replaceChildren(fragment);
};

const renderScreenshot = (screenshot) => {
  if (!screenshot) {
    DOM.screenImage.hidden = true;
    DOM.screenEmpty.hidden = false;
    DOM.canvasStatus.textContent = "No capture";
    DOM.canvasStatus.classList.remove("is-ready");
    return;
  }
  const source = "data:image/jpeg;base64," + screenshot;
  if (DOM.screenImage.src !== source) DOM.screenImage.src = source;
  DOM.screenDialogImage.src = source;
  DOM.screenImage.hidden = false;
  DOM.screenEmpty.hidden = true;
  DOM.canvasStatus.textContent = "Current";
  DOM.canvasStatus.classList.add("is-ready");
};

const renderIntervention = (status, action) => {
  const needsInput = status === "hitl";
  DOM.intervention.hidden = !needsInput;
  if (needsInput) DOM.interventionQuestion.textContent = action || "The agent needs your input before it can continue.";
};

const renderHealth = (telemetry, criticReview) => {
  const data = telemetry || {};
  DOM.healthVram.textContent =
    data.free_vram === null || data.free_vram === undefined
      ? "Unavailable"
      : (Number(data.free_vram) / 1024).toFixed(1) + " GB";
  DOM.healthLayers.textContent = String(data.optimal_ngl ?? "—") + " / 28";
  DOM.healthPlanner.textContent = data.planner_active
    ? data.planner_uses_gpu
      ? "GPU lane"
      : "CPU lane"
    : "Standby";
  DOM.healthCritic.textContent = criticReview?.status ? toTitleCase(criticReview.status) : "Standby";
  DOM.healthState.textContent = data.vla_gpu ? "Operational" : "Monitoring";
};

const syncModelFieldPresentation = (clearLegacyLocalPath = false) => {
  const isLocal = DOM.settingModelType.value === "local";
  DOM.settingModelLabel.textContent = isLocal ? "Model file" : "Vision model identifier";
  DOM.settingModelPath.placeholder = isLocal
    ? "models/your-vision-model.gguf"
    : "Enter a vision-capable provider model";
  if (clearLegacyLocalPath && !isLocal && /\.gguf$/i.test(DOM.settingModelPath.value.trim())) {
    DOM.settingModelPath.value = "";
  }
};

const renderSettings = (settings) => {
  if (!settings || state.settingsDirty) return;
  DOM.settingModelType.value = settings.model_type || "local";
  DOM.settingTemperature.value = settings.temperature ?? 0.2;
  DOM.settingModelPath.value = settings.model_path || "";
  DOM.settingMaxSteps.value = settings.max_steps ?? 15;
  DOM.settingRecording.checked = Boolean(settings.enable_recording);
  DOM.settingApiKey.value = "";
  syncModelFieldPresentation();
};

const renderSafety = (safety, mobile, access) => {
  const policy = safety || {};
  const mode = policy.mode || "supervised";
  const canManagePolicy = Boolean(access?.is_local);
  document.querySelectorAll('input[name="safety-mode"]').forEach((input) => {
    if (!state.policyDirty) input.checked = input.value === mode;
    input.disabled = !canManagePolicy;
  });
  if (!state.policyDirty) {
    DOM.requireApproval.checked = Boolean(policy.require_plan_approval);
    DOM.remoteControl.checked = Boolean(policy.remote_control_enabled);
  }
  DOM.requireApproval.disabled = !canManagePolicy;
  DOM.remoteControl.disabled = !canManagePolicy;
  DOM.savePolicy.disabled = !canManagePolicy;
  DOM.policyState.textContent = toTitleCase(mode);
  DOM.pairingState.textContent = mobile?.network_enabled ? "LAN ready" : "Local only";
  DOM.pairingAddress.textContent = mobile?.network_enabled
    ? mobile.lan_url || "LAN address unavailable"
    : "Set OMNIVLA_HOST=0.0.0.0";
};

const renderStatus = (data) => {
  state.status = data;
  hidePairingPrompt();

  const phase = data.paused ? "paused" : data.phase || data.status;
  setStatusPresentation(data.status, phase, data.paused);
  const recordedActions = Array.isArray(data.steps) ? data.steps.length : 0;
  DOM.metricStep.textContent = recordedActions ? String(recordedActions) : "—";
  DOM.metricLatency.textContent = formatDuration(data.timing?.last_step_ms);
  DOM.metricModel.textContent = toTitleCase(data.settings?.model_type || "local");
  DOM.activeAction.replaceChildren(
    createElement("span", { className: "active-marker", text: "▲" }),
    createElement("p", { text: data.current_action || "Ready for a reviewed task." })
  );

  const isWorking = WORKING_STATES.has(phase) || WORKING_STATES.has(data.status);
  const canRetry = Boolean(data.current_task) && !isWorking;
  DOM.pauseButton.disabled = !isWorking && !data.paused;
  DOM.pauseButton.textContent = data.paused ? "Resume" : "Pause";
  DOM.retryButton.disabled = !canRetry;
  DOM.stopButton.disabled = !isWorking;

  renderConversations(data.chats || [], data.active_chat_id);
  renderPlan(data.active_plan, data.status);
  renderTimeline(data.steps);
  renderAudit(data.audit_events);
  DOM.console.textContent =
    Array.isArray(data.logs) && data.logs.length ? data.logs.slice(-80).join("\n") : "No runtime signals yet.";
  renderScreenshot(data.latest_screenshot_b64);
  renderIntervention(phase, data.current_action);
  renderHealth(data.telemetry, data.critic_review);
  renderSettings(data.settings);
  renderSafety(data.safety, data.mobile, data.access);

  const policyText = data.safety?.require_plan_approval ? "Plan review required" : "Plan review is optional";
  document.querySelector("#composer-policy").textContent = policyText;
};

const refreshStatus = async () => {
  if (state.statusRequestInFlight) return;
  state.statusRequestInFlight = true;
  try {
    const data = await api("/api/status");
    renderStatus(data);
  } catch (error) {
    if (error.status === 401) {
      DOM.statusDot.className = "status-dot";
      DOM.statusLabel.textContent = "Pairing required";
      showPairingPrompt();
    } else {
      DOM.statusDot.className = "status-dot";
      DOM.statusLabel.textContent = "Offline";
    }
  } finally {
    state.statusRequestInFlight = false;
  }
};

const fetchPairingDetails = async () => {
  if (!state.status?.access?.is_local) return;
  try {
    const details = await api("/api/pairing");
    state.pairingDetails = details;
    DOM.pairingToken.textContent = details.token || "Unavailable";
    DOM.pairingExpiry.textContent = formatExpiry(details.expires_in_seconds);
  } catch {
    DOM.pairingToken.textContent = "Unavailable";
    DOM.pairingExpiry.textContent = "—";
  }
};

const submitDraft = async () => {
  const intent = DOM.taskInput.value.trim();
  if (!intent) {
    showToast("Describe the desktop task before drafting a plan.");
    DOM.taskInput.focus();
    return;
  }
  setButtonBusy(DOM.draftPlan, true, "Drafting…");
  try {
    await api("/api/chat", { method: "POST", body: JSON.stringify({ message: intent }) });
    DOM.planState.textContent = "Drafting";
    DOM.planFooter.hidden = true;
    showToast("Planner is drafting a reviewed runbook.", "success");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  } finally {
    setButtonBusy(DOM.draftPlan, false);
  }
};

const requestApproval = (task, sourceTask, risk) => {
  if (!task) {
    showToast("Draft a plan before starting a run.");
    return;
  }
  state.pendingApproval = { task, sourceTask, risk: risk || { reasons: [] } };
  const reasons = risk?.reasons || [];
  DOM.approvalCopy.textContent = reasons.length
    ? "This run includes high-impact intent. Confirm that you want OmniVLA to proceed with the reviewed plan."
    : "OmniVLA will begin executing the reviewed plan on this desktop.";
  DOM.approvalRisks.replaceChildren(
    ...reasons.map((reason) => createElement("li", { text: "May involve " + reason + "." }))
  );
  DOM.approvalDialog.showModal();
};

const confirmApproval = async (event) => {
  event.preventDefault();
  if (!state.pendingApproval) return;
  const pending = state.pendingApproval;
  setButtonBusy(DOM.confirmApproval, true, "Starting…");
  try {
    await api("/api/confirm", {
      method: "POST",
      body: JSON.stringify({
        task: pending.task,
        source_task: pending.sourceTask || pending.task,
        approved: true,
        risk_acknowledged: true,
      }),
    });
    DOM.approvalDialog.close();
    state.pendingApproval = null;
    showToast("Run approved. OmniVLA is taking the first step.", "success");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  } finally {
    setButtonBusy(DOM.confirmApproval, false);
  }
};

const newChat = async () => {
  try {
    await api("/api/chats/new", { method: "POST", body: "{}" });
    DOM.taskInput.value = "";
    await refreshStatus();
    openView("workbench");
    DOM.taskInput.focus();
  } catch (error) {
    showToast(error.message);
  }
};

const switchChat = async (chatId) => {
  try {
    await api("/api/chats/switch", { method: "POST", body: JSON.stringify({ id: chatId }) });
    await refreshStatus();
    openView("workbench");
  } catch (error) {
    showToast(error.message);
  }
};

const pauseOrResume = async () => {
  const endpoint = state.status?.paused ? "/api/resume" : "/api/pause";
  try {
    await api(endpoint, { method: "POST", body: "{}" });
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
};

const stopRun = async () => {
  if (!window.confirm("Stop the active run? The agent will halt at the next safe boundary.")) return;
  try {
    await api("/api/stop", { method: "POST", body: "{}" });
    showToast("Stop request sent.");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
};

const reexecute = async () => {
  if (!state.status?.current_task) return;
  try {
    await api("/api/chats/retry", { method: "POST", body: "{}" });
    await refreshStatus();
    if (!state.activePlan) {
      showToast("The retry plan could not be loaded.");
      return;
    }
    requestApproval(state.activePlan.execution_task, state.activePlan.source_task, state.activePlan.risk);
  } catch (error) {
    showToast(error.message);
  }
};

const submitIntervention = async () => {
  const response = DOM.interventionInput.value.trim();
  if (!response) {
    DOM.interventionInput.focus();
    showToast("Type the input the agent needs before continuing.");
    return;
  }
  try {
    await api("/api/hitl_submit", { method: "POST", body: JSON.stringify({ response }) });
    DOM.interventionInput.value = "";
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
};

const savePolicy = async () => {
  if (!requireLocalControl()) return;
  const selectedMode = document.querySelector('input[name="safety-mode"]:checked')?.value || "supervised";
  setButtonBusy(DOM.savePolicy, true, "Saving…");
  try {
    await api("/api/safety", {
      method: "POST",
      body: JSON.stringify({
        mode: selectedMode,
        require_plan_approval: DOM.requireApproval.checked,
        remote_control_enabled: DOM.remoteControl.checked,
      }),
    });
    state.policyDirty = false;
    showToast("Execution policy saved.", "success");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  } finally {
    setButtonBusy(DOM.savePolicy, false);
  }
};

const rotatePairing = async () => {
  if (!requireLocalControl()) return;
  try {
    const details = await api("/api/pairing/rotate", { method: "POST", body: "{}" });
    state.pairingDetails = details;
    DOM.pairingToken.textContent = details.token;
    DOM.pairingExpiry.textContent = formatExpiry(details.expires_in_seconds);
    showToast("Pairing code rotated.", "success");
  } catch (error) {
    showToast(error.message);
  }
};

const copyToClipboard = async (value, successMessage) => {
  if (!value) {
    showToast("Nothing to copy yet.");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    showToast(successMessage, "success");
  } catch {
    showToast("Clipboard access was unavailable.");
  }
};

const saveSettings = async (event) => {
  event.preventDefault();
  const payload = {
    model_type: DOM.settingModelType.value,
    temperature: Number(DOM.settingTemperature.value),
    model_path: DOM.settingModelPath.value,
    max_steps: Number(DOM.settingMaxSteps.value),
    enable_recording: DOM.settingRecording.checked,
    api_key: DOM.settingApiKey.value,
  };
  const submitButton = DOM.settingsForm.querySelector('button[type="submit"]');
  setButtonBusy(submitButton, true, "Saving…");
  try {
    await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
    state.settingsDirty = false;
    DOM.settingApiKey.value = "";
    showToast("Execution environment saved. Provider key remains runtime-only.", "success");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  } finally {
    setButtonBusy(submitButton, false);
  }
};

const clearVram = async () => {
  if (!requireLocalControl()) return;
  if (!window.confirm("Restart the local VLA server and recycle its model memory?")) return;
  try {
    await api("/api/clear_vram", { method: "POST", body: "{}" });
    showToast("Model memory recycling started.");
  } catch (error) {
    showToast(error.message);
  }
};

const openScreen = () => {
  if (DOM.screenImage.hidden || !DOM.screenDialogImage.src) return;
  DOM.screenDialog.showModal();
};

const dispatchAction = (action) => {
  const handlers = {
    "new-chat": newChat,
    "use-example": () => {
      DOM.taskInput.value = "Open the monthly report, extract the three latest figures, and prepare a concise summary.";
      DOM.taskInput.focus();
    },
    "open-safety": () => openView("safety"),
    refresh: refreshStatus,
    "toggle-pause": pauseOrResume,
    reexecute,
    stop: stopRun,
    "submit-intervention": submitIntervention,
    "clear-vram": clearVram,
    "rotate-pairing": rotatePairing,
    "copy-pairing": () => copyToClipboard(state.pairingDetails?.token, "Pairing code copied."),
    "copy-logs": () => copyToClipboard(DOM.console.textContent, "Runtime signal copy ready."),
    "open-screen": openScreen,
  };
  handlers[action]?.();
};

const bindEvents = () => {
  document.addEventListener("click", (event) => {
    const actionTarget = event.target.closest("[data-action]");
    if (actionTarget) {
      event.preventDefault();
      dispatchAction(actionTarget.dataset.action);
      return;
    }

    const viewTarget = event.target.closest("[data-view-target]");
    if (viewTarget) {
      event.preventDefault();
      openView(viewTarget.dataset.viewTarget);
      return;
    }

    const chatTarget = event.target.closest("[data-chat-id]");
    if (chatTarget) {
      void switchChat(chatTarget.dataset.chatId);
      return;
    }

    const windowTarget = event.target.closest("[data-window-action]");
    if (windowTarget && window.desktopAPI?.windowControl) {
      window.desktopAPI.windowControl(windowTarget.dataset.windowAction);
    }
  });

  DOM.draftPlan.addEventListener("click", () => void submitDraft());
  DOM.approvePlan.addEventListener("click", () => {
    if (!state.activePlan) return;
    requestApproval(state.activePlan.execution_task, state.activePlan.source_task, state.activePlan.risk);
  });
  DOM.confirmApproval.addEventListener("click", (event) => void confirmApproval(event));
  DOM.settingsForm.addEventListener("submit", (event) => void saveSettings(event));
  DOM.settingsForm.addEventListener("input", () => {
    state.settingsDirty = true;
  });
  DOM.settingModelType.addEventListener("change", () => {
    state.settingsDirty = true;
    syncModelFieldPresentation(true);
  });
  document.querySelectorAll('input[name="safety-mode"], #require-approval, #remote-control').forEach((control) => {
    control.addEventListener("change", () => {
      state.policyDirty = true;
    });
  });
  DOM.savePolicy.addEventListener("click", () => void savePolicy());
  DOM.pairingForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const token = DOM.pairingCode.value.trim();
    if (!token) return;
    state.pairingToken = token;
    sessionStorage.setItem("omnivla-pairing-token", token);
    void refreshStatus();
  });
  DOM.taskInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void submitDraft();
    }
  });

  window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      void newChat();
    }
    if (event.key === "Escape" && WORKING_STATES.has(state.status?.status) && !DOM.approvalDialog.open) {
      void pauseOrResume();
    }
  });

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.installPrompt = event;
    DOM.installButton.hidden = false;
  });
  DOM.installButton.addEventListener("click", async () => {
    if (!state.installPrompt) return;
    state.installPrompt.prompt();
    await state.installPrompt.userChoice;
    state.installPrompt = null;
    DOM.installButton.hidden = true;
  });
};

const initialize = () => {
  const pairingFromUrl = new URLSearchParams(window.location.search).get("pair");
  if (pairingFromUrl) {
    state.pairingToken = pairingFromUrl;
    sessionStorage.setItem("omnivla-pairing-token", pairingFromUrl);
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  bindEvents();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }
  void refreshStatus();

  const poll = async () => {
    await refreshStatus();
    const delay = WORKING_STATES.has(state.status?.status) ? 600 : 1500;
    window.setTimeout(poll, delay);
  };
  window.setTimeout(poll, 1500);
};

initialize();

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const WORKING_PHASES = new Set(["thinking", "acting", "verifying", "hitl", "paused", "stopping", "running"]);
  const SKILL_TEMPLATE = `---
name: new_skill
title: New skill
description: Describe the reusable outcome.
domain: desktop
triggers:
  - "example request"
parameters: []
tags: [desktop]
---

# New skill

## Steps
1. Focus the target application.
2. Locate the control by its visible label or role.
3. Complete the action and verify the result.

## Visual cues
- Describe stable labels, icons, and states.

## Recovery
- If the target is unclear, ask for help instead of guessing.
`;

  const state = {
    status: null,
    workspace: "chat",
    skillTab: "library",
    skills: [],
    editingSkill: null,
    currentScreen: null,
    currentScreenStep: null,
    recording: false,
    recordingStartedAt: 0,
    recordingTimer: null,
    menuChatId: null,
    pollTimer: null,
    screenTimer: null,
    requestInFlight: false,
    settingsSignature: "",
    renderSignatures: {},
  };

  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}" /></svg>`;
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function inlineMarkdown(value) {
    return escapeHtml(value)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  function renderMarkdown(value) {
    const lines = String(value || "").replace(/\r/g, "").split("\n");
    const output = [];
    let list = null;
    const closeList = () => {
      if (list) output.push(`</${list}>`);
      list = null;
    };
    lines.forEach((line) => {
      const numbered = line.match(/^\s*\d+[.)]\s+(.+)/);
      const bullet = line.match(/^\s*[-*]\s+(.+)/);
      if (numbered || bullet) {
        const next = numbered ? "ol" : "ul";
        if (list !== next) {
          closeList();
          list = next;
          output.push(`<${list}>`);
        }
        output.push(`<li>${inlineMarkdown((numbered || bullet)[1])}</li>`);
        return;
      }
      closeList();
      if (!line.trim()) return;
      const heading = line.match(/^#{1,4}\s+(.+)/);
      if (heading) output.push(`<h3>${inlineMarkdown(heading[1])}</h3>`);
      else output.push(`<p>${inlineMarkdown(line)}</p>`);
    });
    closeList();
    return output.join("");
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const request = { cache: "no-store", ...options, headers };
    if (request.body !== undefined) {
      headers.set("Content-Type", "application/json");
      if (typeof request.body !== "string") request.body = JSON.stringify(request.body);
    }
    const response = await fetch(path, request);
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* empty response */ }
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    return payload;
  }

  function toast(message, isError = false) {
    const item = document.createElement("div");
    item.className = `toast${isError ? " is-error" : ""}`;
    item.textContent = message;
    $("toast-region").append(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (!button.dataset.label) button.dataset.label = button.querySelector("span")?.textContent.trim() || button.getAttribute("aria-label") || button.textContent.trim();
    button.disabled = busy;
    button.classList.toggle("is-busy", busy);
    const text = button.querySelector("span");
    if (text) text.textContent = busy ? label : button.dataset.label;
    else if (!button.children.length) button.textContent = busy ? label : button.dataset.label;
    else button.setAttribute("aria-label", busy ? label : button.dataset.label);
  }

  function humanStatus(value) {
    const labels = {
      draft: "Ready", idle: "Ready", ready: "Plan ready", plan_created: "Plan ready",
      planning: "Planning", thinking: "Working", acting: "Working", verifying: "Checking",
      running: "Working", hitl: "Input needed", paused: "Paused", stopping: "Stopping",
      success: "Done", done: "Done", failed: "Needs attention", error: "Needs attention", stopped: "Stopped",
    };
    return labels[String(value || "idle").toLowerCase()] || "Ready";
  }

  function phaseTone(value) {
    const phase = String(value || "idle").toLowerCase();
    if (["done", "success"].includes(phase)) return "success";
    if (["failed", "error", "hitl"].includes(phase)) return "attention";
    if (["stopped", "paused"].includes(phase)) return "paused";
    if (WORKING_PHASES.has(phase) || phase === "planning") return "working";
    return "idle";
  }

  function formatElapsed(startedAt) {
    const start = Number(startedAt);
    if (!Number.isFinite(start) || start <= 0) return "";
    const seconds = Math.max(0, Math.floor(Date.now() / 1000 - start));
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function formatAction(value) {
    const action = String(value || "").replaceAll("_", " ").trim();
    if (!action) return "Waiting";
    const labels = {
      click: "Click a control", double_click: "Open an item", right_click: "Open a menu",
      type: "Enter text", key_press: "Press a key", wait: "Wait for the screen",
      scroll: "Scroll", switch_to_app: "Switch apps", terminate: "Finish",
      get_open_apps: "Check open apps", minimize_all_apps: "Show the desktop",
    };
    return labels[action.replaceAll(" ", "_")] || action.charAt(0).toUpperCase() + action.slice(1);
  }

  function isSelectedExecution(data = state.status) {
    return Boolean(data?.active_chat_id && data?.execution_live?.execution_chat_id === data.active_chat_id);
  }

  function isLiveWorking(data = state.status) {
    const live = data?.execution_live || {};
    return Boolean(live.execution_chat_id && (WORKING_PHASES.has(live.phase) || WORKING_PHASES.has(live.status)));
  }

  function closeMobileSidebar() {
    document.body.classList.remove("sidebar-open");
    $("sidebar-scrim").hidden = true;
  }

  function transitionUI(update) {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduceMotion && typeof document.startViewTransition === "function") {
      try { document.startViewTransition(update); return; } catch (_) { /* fall through */ }
    }
    update();
  }

  function openWorkspace(name) {
    state.workspace = name;
    transitionUI(() => {
      document.querySelectorAll("[data-workspace-view]").forEach((view) => {
        view.classList.toggle("is-active", view.dataset.workspaceView === name);
      });
    });
    closeMobileSidebar();
    if (name === "skills") loadSkills();
    if (name === "chat") window.setTimeout(() => $("composer-input").focus(), 0);
  }

  function openSkillTab(name) {
    state.skillTab = name;
    transitionUI(() => {
      document.querySelectorAll("[data-skill-tab]").forEach((button) => button.classList.toggle("is-active", button.dataset.skillTab === name));
      document.querySelectorAll("[data-skill-view]").forEach((view) => view.classList.toggle("is-active", view.dataset.skillView === name));
    });
    if (name === "library") loadSkills();
  }

  function renderSidebar(data) {
    const query = $("chat-search").value.trim().toLowerCase();
    const chats = [...(data.chats || [])]
      .filter((chat) => `${chat.title} ${chat.intent}`.toLowerCase().includes(query))
      .sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
    const signature = JSON.stringify([query, data.active_chat_id, data.execution_live?.execution_chat_id, chats.map((chat) => [chat.id, chat.title, chat.status, chat.updated_at])]);
    if (state.renderSignatures.sidebar === signature) return;
    state.renderSignatures.sidebar = signature;
    $("chat-list").innerHTML = chats.length ? chats.map((chat, index) => {
      const active = chat.id === data.active_chat_id;
      const running = chat.id === data.execution_live?.execution_chat_id && isLiveWorking(data);
      return `<div class="chat-row is-entering${active ? " is-active" : ""}" style="--item-index:${index}" data-chat-id="${escapeHtml(chat.id)}"><button class="chat-row-open" type="button"><span class="chat-row-title">${escapeHtml(chat.title || "New chat")}</span><span class="chat-row-meta"><i class="chat-status${running ? " is-running" : ""}" data-tone="${phaseTone(chat.status)}"></i>${escapeHtml(running ? "Working" : humanStatus(chat.status))}</span></button><button class="chat-row-delete" type="button" title="Chat options" aria-label="Options for ${escapeHtml(chat.title || "chat")}">${icon("more")}</button></div>`;
    }).join("") : `<p class="sidebar-empty">No matching chats</p>`;
  }

  function renderHeader(data) {
    const chat = (data.chats || []).find((item) => item.id === data.active_chat_id) || {};
    $("session-title").textContent = data.active_title || chat.title || "New chat";
    $("session-status").textContent = humanStatus(chat.status || data.status);
    $("session-status").dataset.tone = phaseTone(data.phase || chat.status);
    document.title = `${String(data.active_title || "New chat").slice(0, 48)} · OmniVLA`;
    const retryable = ["success", "failed", "stopped"].includes(chat.status) && Boolean(chat.intent);
    $("retry-chat").hidden = !retryable;
    $("delete-chat").disabled = (data.chats || []).length <= 1 || chat.status === "running";
  }

  function renderConversation(data) {
    const history = Array.isArray(data.chat_history) ? data.chat_history : [];
    const planning = data.planning_chat_id === data.active_chat_id;
    const signature = JSON.stringify([data.active_chat_id, history, planning]);
    if (state.renderSignatures.conversation === signature) return;
    const scroller = $("chat-scroll");
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
    const previousChat = state.renderSignatures.conversationChat;
    state.renderSignatures.conversation = signature;
    state.renderSignatures.conversationChat = data.active_chat_id;
    $("chat-empty").hidden = history.some((message) => message.role === "user") || planning;
    const messages = history.map((message, messageIndex) => {
      const role = message.role === "user" ? "user" : "assistant";
      const isPlan = role === "assistant" && (String(message.content || "").match(/^\s*\d+[.)]\s+/gm) || []).length >= 2;
      const choose = isPlan ? `<button class="plan-choice" data-plan-index="${messageIndex}" type="button">${icon("play")}<span>Use this plan</span></button>` : "";
      return `<article class="message is-${role}"><div class="message-avatar" aria-hidden="true">${role === "user" ? "You" : "O"}</div><div class="message-body">${renderMarkdown(message.content)}${choose}</div></article>`;
    });
    if (planning) messages.push(`<article class="message is-assistant is-pending"><div class="message-avatar skeleton-avatar" aria-hidden="true"></div><div class="message-body message-skeleton" aria-label="Preparing a plan"><span></span><span></span><span></span></div></article>`);
    $("conversation").innerHTML = messages.join("");
    if (previousChat !== data.active_chat_id || nearBottom) window.requestAnimationFrame(() => { scroller.scrollTop = scroller.scrollHeight; });
  }

  function renderExecution(data) {
    const phase = String(data.phase || data.status || "idle");
    const tone = phaseTone(phase);
    const elapsed = formatElapsed(data.phase_started_at);
    const activeSelected = isSelectedExecution(data) && isLiveWorking(data);
    const executionSignature = JSON.stringify([
      data.active_chat_id, phase, data.current_action, data.step, data.steps,
      data.active_plan?.plan, Boolean($("risk-ack")?.checked),
    ]);
    if (state.renderSignatures.execution === executionSignature) {
      renderScreenEvidence(data);
      return;
    }
    state.renderSignatures.execution = executionSignature;
    let title = "Ready";
    let detail = "Send a message to prepare a plan.";
    let symbol = icon("panel");
    if (phase === "planning") {
      title = "Preparing a plan"; detail = "This usually takes a few moments."; symbol = `<span class="spinner" aria-hidden="true"></span>`;
    } else if (activeSelected) {
      title = humanStatus(phase); detail = formatAction(data.current_action); symbol = `<span class="spinner" aria-hidden="true"></span>`;
    } else if (data.active_plan) {
      title = "Ready to run"; detail = "Review the plan below before starting."; symbol = icon("check");
    } else if (["done", "success"].includes(phase) || (data.chats || []).find((chat) => chat.id === data.active_chat_id)?.status === "success") {
      title = "Completed"; detail = `${Number(data.step || 0)} action${Number(data.step || 0) === 1 ? "" : "s"}`; symbol = icon("check");
    } else if (["failed", "error"].includes(phase)) {
      title = "Needs attention"; detail = data.current_action || "Review the activity and try again."; symbol = icon("alert");
    } else if (phase === "stopped") {
      title = "Stopped"; detail = "No more actions will start."; symbol = icon("stop");
    }
    $("execution-summary").dataset.tone = tone;
    $("execution-summary").innerHTML = `<div class="summary-icon">${symbol}</div><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div>${elapsed && activeSelected ? `<time>${escapeHtml(elapsed)}</time>` : ""}`;
    $("execution-subtitle").textContent = title;

    const plan = data.active_plan;
    $("approval").hidden = !plan;
    if (plan) {
      $("plan-copy").innerHTML = renderMarkdown(plan.plan);
      const highRisk = Boolean(plan.risk?.requires_explicit_acknowledgement);
      $("risk-badge").textContent = highRisk ? "Review" : "Ready";
      $("risk-badge").dataset.tone = highRisk ? "attention" : "success";
      $("risk-ack-wrap").hidden = !highRisk;
      $("risk-copy").textContent = highRisk ? (plan.risk.reasons || []).join(", ") : "";
      $("run-plan").disabled = highRisk && !$("risk-ack").checked;
    }

    const needsInput = phase === "hitl" && activeSelected;
    $("operator-request").hidden = !needsInput;
    if (needsInput) $("operator-question").textContent = data.current_action || "Please review the current screen.";

    const steps = Array.isArray(data.steps) ? data.steps : [];
    $("activity-count").textContent = `${steps.length} ${steps.length === 1 ? "action" : "actions"}`;
    $("activity-empty").hidden = steps.length > 0;
    const renderedSteps = steps.map((step) => {
      const successful = step.success !== false && !["STRAYING", "HITL"].includes(String(step.eval_state || "").toUpperCase());
      const copy = step.action_text || formatAction(step.action);
      return `<li style="--item-index:${steps.indexOf(step)}"><span class="activity-check" data-tone="${successful ? "success" : "attention"}">${icon(successful ? "check" : "alert")}</span><div><strong>${escapeHtml(copy)}</strong>${step.output ? `<p>${escapeHtml(step.output)}</p>` : ""}</div><span class="activity-index">${Number(step.step || 0)}</span></li>`;
    }).join("");
    const nextStep = activeSelected ? `<li class="activity-skeleton" aria-label="Preparing next action"><span class="skeleton-orb"></span><div><i></i><i></i></div></li>` : "";
    $("activity-list").innerHTML = renderedSteps + nextStep;

    $("execution-controls").hidden = !activeSelected;
    $("pause-run").querySelector("span").textContent = data.paused ? "Resume" : "Pause";
    $("pause-run").querySelector("use").setAttribute("href", data.paused ? "#i-play" : "#i-pause");
    renderScreenEvidence(data);
  }

  function renderScreenEvidence(data) {
    const show = Boolean(state.currentScreen && isSelectedExecution(data));
    $("screen-evidence").hidden = !show;
    if (!show) return;
    const source = `data:image/jpeg;base64,${state.currentScreen}`;
    if ($("latest-screen").src !== source) $("latest-screen").src = source;
    $("screen-step").textContent = state.currentScreenStep ? `Action ${state.currentScreenStep}` : "";
  }

  function renderComposer(data) {
    const blocked = isLiveWorking(data) || data.planning_chat_id === data.active_chat_id;
    const hasText = Boolean($("composer-input").value.trim());
    $("send-message").disabled = blocked || !hasText;
    $("composer-input").disabled = blocked;
    $("composer-input").placeholder = blocked ? "Finish the current task before sending another message" : "Ask OmniVLA to do something on your computer";
    $("composer-hint").textContent = blocked ? "One task runs at a time on this computer" : "Enter to send · Shift Enter for a new line";
  }

  function renderLocalState(data) {
    const telemetry = data.telemetry || {};
    // The planner intentionally loads only while preparing a plan. Requiring
    // it to remain resident made a healthy idle app look permanently busy.
    const ready = Boolean(telemetry.vla_gpu);
    $("local-state-label").textContent = ready ? "Ready" : "Starting";
    $("local-state-dot").dataset.state = ready ? "ready" : "starting";
    $("settings-service-label").textContent = ready ? "Ready for tasks" : "Getting ready";
    $("settings-service-dot").dataset.state = ready ? "ready" : "starting";
  }

  function renderSettings(data) {
    const signature = JSON.stringify([data.settings, data.safety]);
    if (state.settingsSignature === signature || $("settings-form").contains(document.activeElement)) return;
    state.settingsSignature = signature;
    $("max-steps").value = data.settings?.max_steps ?? 60;
    $("memory-enabled").checked = Boolean(data.settings?.memory_enabled);
    $("enable-recording").checked = Boolean(data.settings?.enable_recording);
    $("safety-mode").value = data.safety?.mode || "supervised";
    $("require-plan-approval").checked = data.safety?.require_plan_approval !== false;
  }

  function renderStatus(data) {
    state.status = data;
    document.body.dataset.executionTone = phaseTone(data.phase || data.status);
    renderSidebar(data);
    renderHeader(data);
    renderConversation(data);
    renderExecution(data);
    renderComposer(data);
    renderLocalState(data);
    renderSettings(data);
  }

  async function fetchStatus() {
    if (state.requestInFlight) return;
    state.requestInFlight = true;
    try {
      renderStatus(await api("/api/status"));
    } catch (error) {
      $("local-state-label").textContent = "Unavailable";
      $("local-state-dot").dataset.state = "error";
    } finally {
      state.requestInFlight = false;
      const quick = state.status?.planning_chat_id || isLiveWorking(state.status);
      state.pollTimer = window.setTimeout(fetchStatus, document.hidden ? 5000 : (quick ? 900 : 2200));
    }
  }

  async function fetchScreen() {
    try {
      if (state.status && isSelectedExecution(state.status)) {
        const result = await api("/api/screen");
        state.currentScreen = result.screenshot_b64 || null;
        state.currentScreenStep = result.step || null;
      } else {
        state.currentScreen = null;
        state.currentScreenStep = null;
      }
      if (state.status) renderScreenEvidence(state.status);
    } catch (_) { /* execution can finish between status and frame requests */ }
    state.screenTimer = window.setTimeout(fetchScreen, document.hidden ? 6000 : (isLiveWorking(state.status) ? 1600 : 4000));
  }

  async function sendMessage() {
    const input = $("composer-input");
    const message = input.value.trim();
    if (!message || isLiveWorking(state.status)) return;
    setBusy($("send-message"), true, "Sending");
    try {
      await api("/api/chat", { method: "POST", body: { message, chat_id: state.status?.active_chat_id } });
      input.value = "";
      resizeComposer();
      await fetchStatus();
    } catch (error) { toast(error.message, true); }
    finally { setBusy($("send-message"), false); renderComposer(state.status || {}); }
  }

  async function createChat() {
    try {
      await api("/api/chats/new", { method: "POST", body: {} });
      state.currentScreen = null;
      state.renderSignatures = {};
      openWorkspace("chat");
      await fetchStatus();
    } catch (error) { toast(error.message, true); }
  }

  async function switchChat(id) {
    if (!id || id === state.status?.active_chat_id) return closeMobileSidebar();
    try {
      await api("/api/chats/switch", { method: "POST", body: { id } });
      state.currentScreen = null;
      state.renderSignatures = {};
      openWorkspace("chat");
      await fetchStatus();
    } catch (error) { toast(error.message, true); }
  }

  async function deleteChat(id = state.status?.active_chat_id) {
    if (!id || !window.confirm("Delete this chat?")) return;
    try {
      await api("/api/chats/delete", { method: "POST", body: { id } });
      state.renderSignatures = {};
      await fetchStatus();
    } catch (error) { toast(error.message, true); }
  }

  function openChatMenu(button, chatId) {
    const menu = $("chat-menu");
    if (!menu.hidden && state.menuChatId === chatId) { menu.hidden = true; state.menuChatId = null; return; }
    const rect = button.getBoundingClientRect();
    state.menuChatId = chatId;
    menu.style.left = `${Math.min(window.innerWidth - 166, rect.right + 5)}px`;
    menu.style.top = `${Math.min(window.innerHeight - 52, rect.top)}px`;
    menu.hidden = false;
  }

  async function selectPlan(messageIndex) {
    const plan = state.status?.chat_history?.[Number(messageIndex)]?.content;
    if (!plan) return;
    try {
      await api("/api/plans/select", { method: "POST", body: { chat_id: state.status.active_chat_id, plan } });
      state.renderSignatures = {};
      await fetchStatus();
      toast("Plan selected for review.");
    } catch (error) { toast(error.message, true); }
  }

  async function retryChat() {
    try {
      await api("/api/chats/retry", { method: "POST", body: {} });
      state.renderSignatures = {};
      await fetchStatus();
      toast("Retry ready for review.");
    } catch (error) { toast(error.message, true); }
  }

  async function runPlan() {
    const plan = state.status?.active_plan;
    if (!plan) return;
    const highRisk = Boolean(plan.risk?.requires_explicit_acknowledgement);
    if (highRisk && !$("risk-ack").checked) return;
    setBusy($("run-plan"), true, "Starting");
    try {
      await api("/api/confirm", { method: "POST", body: {
        task: plan.execution_task,
        source_task: plan.source_task,
        approved: true,
        risk_acknowledged: !highRisk || $("risk-ack").checked,
        chat_id: state.status.active_chat_id,
      } });
      await fetchStatus();
    } catch (error) { toast(error.message, true); }
    finally { setBusy($("run-plan"), false); }
  }

  async function togglePause() {
    const paused = Boolean(state.status?.paused);
    try { await api(paused ? "/api/resume" : "/api/pause", { method: "POST", body: {} }); await fetchStatus(); }
    catch (error) { toast(error.message, true); }
  }

  async function stopRun() {
    try { await api("/api/stop", { method: "POST", body: {} }); await fetchStatus(); toast("Task stopped."); }
    catch (error) { toast(error.message, true); }
  }

  function resizeComposer() {
    const input = $("composer-input");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
    renderComposer(state.status || {});
  }

  async function loadSkills() {
    try {
      const result = await api("/api/skills");
      state.skills = result.skills || [];
      renderSkills();
    } catch (error) {
      $("skill-list").innerHTML = `<p class="panel-empty">${escapeHtml(error.message)}</p>`;
    }
  }

  function renderSkills() {
    const query = $("skill-search").value.trim().toLowerCase();
    const skills = state.skills.filter((skill) => [skill.name, skill.title, skill.description, ...(skill.tags || [])].join(" ").toLowerCase().includes(query));
    $("skill-list").innerHTML = skills.length ? skills.map((skill) => `<button class="skill-row" data-skill-name="${escapeHtml(skill.name)}" type="button"><div><strong>${escapeHtml(skill.title || skill.name)}</strong><p>${escapeHtml(skill.description || "No description")}</p></div><span>${escapeHtml(skill.domain || "desktop")}</span></button>`).join("") : `<div class="utility-empty"><span class="empty-mark"><i></i><i></i></span><h2>${query ? "No matching skills" : "No skills yet"}</h2><p>${query ? "Try another search." : "Create one with Markdown or teach a workflow by example."}</p></div>`;
  }

  function startSkillEditor(skill = null) {
    state.editingSkill = skill?.name || null;
    $("skill-editor-title").textContent = skill ? skill.title || skill.name : "New skill";
    $("skill-markdown").value = skill?.raw_markdown || SKILL_TEMPLATE;
    $("delete-skill").hidden = !skill;
    $("skill-save-state").textContent = "";
    openSkillTab("editor");
    window.setTimeout(() => $("skill-markdown").focus(), 0);
  }

  async function saveSkill() {
    const markdown = $("skill-markdown").value.trim();
    if (!markdown) return toast("Add the skill Markdown first.", true);
    try {
      await api("/api/skills", { method: "POST", body: { markdown } });
      $("skill-save-state").textContent = "Saved";
      await loadSkills();
      openSkillTab("library");
      toast("Skill saved.");
    } catch (error) { $("skill-save-state").textContent = error.message; toast(error.message, true); }
  }

  async function deleteSkill() {
    if (!state.editingSkill || !window.confirm(`Delete “${state.editingSkill}”?`)) return;
    try {
      await api("/api/skills/delete", { method: "POST", body: { name: state.editingSkill } });
      state.editingSkill = null;
      await loadSkills();
      openSkillTab("library");
      toast("Skill deleted.");
    } catch (error) { toast(error.message, true); }
  }

  async function importSkillFile(file) {
    if (!file) return;
    const extension = file.name.toLowerCase().split(".").pop();
    if (!["md", "markdown", "mds"].includes(extension)) return toast("Choose a .md, .markdown, or .mds file.", true);
    if (file.size > 48000) return toast("Skill files must be smaller than 48 KB.", true);
    try {
      $("skill-markdown").value = await file.text();
      state.editingSkill = null;
      $("skill-editor-title").textContent = file.name;
      $("delete-skill").hidden = true;
      openSkillTab("editor");
    } catch (_) { toast("The file could not be read.", true); }
  }

  function updateRecordingTime() {
    if (!state.recording) return;
    const seconds = Math.floor((Date.now() - state.recordingStartedAt) / 1000);
    $("recording-time").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function syncRecordingButton() {
    if (!state.recording) $("toggle-recording").disabled = !$("teach-goal").value.trim();
  }

  async function toggleRecording() {
    const button = $("toggle-recording");
    if (!state.recording) {
      const goal = $("teach-goal").value.trim();
      if (!goal) return toast("Describe the workflow first.", true);
      setBusy(button, true, "Starting");
      try {
        await api("/api/observe/start", { method: "POST", body: { task_goal: goal } });
        state.recording = true;
        state.recordingStartedAt = Date.now();
        button.dataset.label = "Start demonstration";
        button.classList.add("is-recording");
        button.querySelector("span").textContent = "Stop demonstration";
        button.disabled = false;
        $("recording-status").hidden = false;
        $("captured-count").textContent = "0";
        $("captured-list").innerHTML = `<p class="panel-empty">Recording clicks, app changes, and shortcuts.</p>`;
        $("create-from-demo").hidden = true;
        state.recordingTimer = window.setInterval(updateRecordingTime, 500);
      } catch (error) { toast(error.message, true); setBusy(button, false); syncRecordingButton(); }
      return;
    }

    setBusy(button, true, "Stopping");
    try {
      const result = await api("/api/observe/stop", { method: "POST", body: {} });
      const actions = result.demonstration?.actions || [];
      state.recording = false;
      window.clearInterval(state.recordingTimer);
      button.classList.remove("is-recording");
      button.disabled = false;
      button.querySelector("span").textContent = "Start demonstration";
      $("recording-status").hidden = true;
      $("captured-count").textContent = String(actions.length);
      $("captured-list").innerHTML = actions.length ? actions.slice(0, 60).map((action, index) => `<div class="captured-row" style="animation-delay:${Math.min(index * 28, 220)}ms"><span>${index + 1}</span><div><strong>${escapeHtml(formatAction(action.action_type))}</strong><small>${escapeHtml(action.window_title || "Desktop")}${action.text ? " · private value removed" : ""}</small></div></div>`).join("") : `<p class="panel-empty">No input was captured. Try the demonstration again.</p>`;
      $("create-from-demo").hidden = actions.length === 0;
      syncRecordingButton();
    } catch (error) { toast(error.message, true); button.disabled = false; syncRecordingButton(); }
  }

  async function createTaughtSkill() {
    const button = $("create-taught-skill");
    const name = $("taught-skill-name").value.trim();
    setBusy(button, true, "Learning workflow");
    try {
      const result = await api("/api/skills/synthesize", { method: "POST", body: name ? { name } : {} });
      await loadSkills();
      openSkillTab("library");
      toast(`Created ${result.skill?.title || "skill"}.`);
    } catch (error) { toast(error.message, true); }
    finally { setBusy(button, false); }
  }

  async function saveSettings(event) {
    event.preventDefault();
    $("settings-save-state").textContent = "Saving…";
    try {
      await api("/api/settings", { method: "POST", body: {
        max_steps: Number($("max-steps").value),
        memory_enabled: $("memory-enabled").checked,
        enable_recording: $("enable-recording").checked,
      } });
      await api("/api/safety", { method: "POST", body: {
        mode: $("safety-mode").value,
        require_plan_approval: $("require-plan-approval").checked,
      } });
      $("settings-save-state").textContent = "Saved";
      await fetchStatus();
    } catch (error) { $("settings-save-state").textContent = error.message; toast(error.message, true); }
  }

  async function quitApplication() {
    if (!window.confirm("Quit OmniVLA? This stops the active task and releases its memory.")) return;
    const button = $("quit-app");
    setBusy(button, true, "Quitting");
    try {
      if (window.desktopAPI?.quitApp) {
        await window.desktopAPI.quitApp();
      } else {
        await api("/api/shutdown", { method: "POST", body: {} });
        document.body.innerHTML = '<main class="shutdown-screen"><strong>OmniVLA has stopped</strong><p>You can close this window.</p></main>';
      }
    } catch (error) {
      toast(error.message, true);
      setBusy(button, false);
    }
  }

  function bindEvents() {
    document.querySelectorAll("[data-window-control]").forEach((button) => button.addEventListener("click", () => {
      window.desktopAPI?.windowControl?.(button.dataset.windowControl);
    }));
    $("quit-app").addEventListener("click", quitApplication);
    $("new-chat").addEventListener("click", createChat);
    $("chat-search").addEventListener("input", () => state.status && renderSidebar(state.status));
    $("chat-list").addEventListener("click", (event) => {
      const row = event.target.closest("[data-chat-id]");
      if (!row) return;
      if (event.target.closest(".chat-row-delete")) openChatMenu(event.target.closest(".chat-row-delete"), row.dataset.chatId);
      else if (event.target.closest(".chat-row-open")) switchChat(row.dataset.chatId);
    });
    $("menu-delete-chat").addEventListener("click", () => { const id = state.menuChatId; $("chat-menu").hidden = true; state.menuChatId = null; if (id) deleteChat(id); });
    document.addEventListener("click", (event) => { if (!event.target.closest(".chat-row-delete") && !event.target.closest("#chat-menu")) { $("chat-menu").hidden = true; state.menuChatId = null; } });
    $("conversation").addEventListener("click", (event) => {
      const choice = event.target.closest("[data-plan-index]");
      if (choice) selectPlan(choice.dataset.planIndex);
    });
    $("open-sidebar").addEventListener("click", () => { document.body.classList.add("sidebar-open"); $("sidebar-scrim").hidden = false; });
    $("close-sidebar").addEventListener("click", closeMobileSidebar);
    $("sidebar-scrim").addEventListener("click", closeMobileSidebar);
    $("open-skills").addEventListener("click", () => openWorkspace("skills"));
    $("open-settings").addEventListener("click", () => openWorkspace("settings"));
    document.querySelectorAll(".back-to-chat").forEach((button) => button.addEventListener("click", () => openWorkspace("chat")));

    $("composer-form").addEventListener("submit", (event) => { event.preventDefault(); sendMessage(); });
    $("composer-input").addEventListener("input", resizeComposer);
    $("teach-goal").addEventListener("input", syncRecordingButton);
    $("composer-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(); }
    });
    document.querySelectorAll("[data-suggestion]").forEach((button) => button.addEventListener("click", () => { $("composer-input").value = button.dataset.suggestion; resizeComposer(); $("composer-input").focus(); }));

    $("toggle-execution").addEventListener("click", () => document.body.classList.toggle("execution-closed"));
    $("close-execution").addEventListener("click", () => document.body.classList.add("execution-closed"));
    $("delete-chat").addEventListener("click", () => deleteChat());
    $("retry-chat").addEventListener("click", retryChat);
    $("risk-ack").addEventListener("change", () => { state.renderSignatures.execution = null; if (state.status) renderExecution(state.status); });
    $("run-plan").addEventListener("click", runPlan);
    $("pause-run").addEventListener("click", togglePause);
    $("stop-run").addEventListener("click", stopRun);
    $("operator-form").addEventListener("submit", async (event) => {
      event.preventDefault(); const response = $("operator-input").value.trim(); if (!response) return;
      try { await api("/api/hitl_submit", { method: "POST", body: { response } }); $("operator-input").value = ""; await fetchStatus(); }
      catch (error) { toast(error.message, true); }
    });

    document.querySelectorAll("[data-skill-tab]").forEach((button) => button.addEventListener("click", () => openSkillTab(button.dataset.skillTab)));
    $("new-skill").addEventListener("click", () => startSkillEditor());
    $("skill-search").addEventListener("input", renderSkills);
    $("skill-list").addEventListener("click", (event) => { const row = event.target.closest("[data-skill-name]"); if (row) startSkillEditor(state.skills.find((skill) => skill.name === row.dataset.skillName)); });
    $("skill-editor").addEventListener("submit", (event) => { event.preventDefault(); saveSkill(); });
    $("reset-skill").addEventListener("click", () => { $("skill-markdown").value = SKILL_TEMPLATE; state.editingSkill = null; $("delete-skill").hidden = true; });
    $("delete-skill").addEventListener("click", deleteSkill);
    $("skill-file").addEventListener("change", (event) => importSkillFile(event.target.files[0]));
    ["dragenter", "dragover"].forEach((name) => $("import-zone").addEventListener(name, (event) => { event.preventDefault(); $("import-zone").classList.add("is-dragging"); }));
    ["dragleave", "drop"].forEach((name) => $("import-zone").addEventListener(name, (event) => { event.preventDefault(); $("import-zone").classList.remove("is-dragging"); if (name === "drop") importSkillFile(event.dataTransfer.files[0]); }));
    $("toggle-recording").addEventListener("click", toggleRecording);
    $("create-taught-skill").addEventListener("click", createTaughtSkill);

    $("settings-form").addEventListener("submit", saveSettings);
    $("clear-memory").addEventListener("click", async () => {
      if (!window.confirm("Clear locally stored conversation recall? Chat history will remain.")) return;
      try { const result = await api("/api/memory/clear", { method: "POST", body: {} }); toast(`Cleared ${result.stores_cleared} local stores.`); }
      catch (error) { toast(error.message, true); }
    });
    $("restart-models").addEventListener("click", async () => {
      try { await api("/api/clear_vram", { method: "POST", body: {} }); toast("OmniVLA is restarting."); }
      catch (error) { toast(error.message, true); }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "n") { event.preventDefault(); createChat(); }
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "e") { event.preventDefault(); document.body.classList.toggle("execution-closed"); }
      if (event.key === "Escape" && isSelectedExecution(state.status) && isLiveWorking(state.status)) stopRun();
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { window.clearTimeout(state.pollTimer); fetchStatus(); } });
  }

  async function init() {
    if (window.matchMedia("(max-width: 900px)").matches) document.body.classList.add("execution-closed");
    bindEvents();
    resizeComposer();
    await fetchStatus();
    fetchScreen();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  init();
})();

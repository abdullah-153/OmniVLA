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
    autocomplete: { open: false, query: "", selectedIndex: 0, matches: [], triggerPos: 0 },
    latestIntelligentSkill: null,
  };

  let localToken = "";
  let pairingToken = sessionStorage.getItem("omnivla-pairing") || "";
  let authRequest = null;
  const isDesktopHost = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  async function ensureSession() {
    if (!isDesktopHost || localToken) return;
    if (!authRequest) authRequest = fetch("/api/session", { cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error("Desktop session unavailable. Restart or reconnect to OmniVLA.");
      localToken = (await response.json()).token;
    }).finally(() => { authRequest = null; });
    await authRequest;
  }

  let pendingIntervention = null;
  function renderIntervention(data) {
    const request = data.intervention || data.execution_live?.intervention;
    const card = $("intervention-card");
    card.hidden = !request;
    if (!request) { pendingIntervention = null; return; }
    const changed = pendingIntervention?.id !== request.id;
    pendingIntervention = request;
    card.dataset.requestId = request.id;
    $("intervention-question").textContent = request.question;
    const approval = ["approval", "completion"].includes(request.kind);
    $("intervention-title").textContent = request.kind === "completion" ? "Verify the result" : approval ? "Review this action" : "Your input is needed";
    $("intervention-approve").hidden = !approval;
    $("intervention-deny").hidden = false;
    $("intervention-send").hidden = approval;
    $("intervention-input-wrap").hidden = approval;
    $("intervention-input").type = request.kind === "secret" ? "password" : "text";
    $("intervention-input-label").textContent = request.kind === "secret" ? "Verification code" : "Response";
    const readOnly = data.access?.is_local === false && !data.access?.remote_control_enabled;
    card.querySelectorAll("button, input").forEach(control => { control.disabled = readOnly; });
    if (readOnly) $("intervention-error").textContent = "Read-only companion. Respond on the desktop.";
    if (changed) { $("intervention-input").value = ""; if (!readOnly) $("intervention-error").textContent = ""; }
  }
  async function answerIntervention(response) {
    if (!pendingIntervention) return;
    const request = { ...pendingIntervention, response };
    try {
      await api("/api/hitl_submit", { method: "POST", body: request });
      $("intervention-input").value = "";
      $("intervention-card").hidden = true;
      await fetchStatus();
    } catch (error) { $("intervention-error").textContent = error.message; }
  }
  $("intervention-approve").addEventListener("click", () => answerIntervention("approve"));
  $("intervention-deny").addEventListener("click", () => answerIntervention("deny"));
  $("intervention-form").addEventListener("submit", event => { event.preventDefault(); answerIntervention($("intervention-input").value); });
  $("pairing-form").addEventListener("submit", async event => {
    event.preventDefault(); pairingToken = $("pairing-input").value.trim();
    try {
      const data = await api("/api/status");
      sessionStorage.setItem("omnivla-pairing", pairingToken);
      $("pairing-input").value = ""; $("pairing-card").hidden = true;
      renderStatus(data);
    } catch (error) { $("pairing-error").textContent = error.message; }
  });
  $("pairing-show").addEventListener("click", async () => {
    try {
      const pairing = await api("/api/pairing/rotate", { method: "POST", body: {} });
      const mobile = state.status?.mobile || {};
      $("pairing-details").textContent = `Code: ${pairing.token} · Expires ${new Date(pairing.expires_at * 1000).toLocaleTimeString()}. ${mobile.lan_url || "To use a companion, restart the server with OMNIVLA_HOST=0.0.0.0 on a trusted network."}`;
    } catch (error) { $("pairing-details").textContent = error.message; }
  });
  $("clear-personal-memory").addEventListener("click", async () => {
    if (!window.confirm("Forget learned personal context and successful workflows? Preferences saved in Settings are kept.")) return;
    try { await api("/api/profile", { method: "POST", body: { clear_learned: true } }); await fetchStatus(); }
    catch (error) { toast(error.message, true); }
  });
  for (const [listId, field] of [["memory-entities", "delete_entity_id"], ["memory-relations", "delete_relation_id"], ["memory-provenance", "delete_record_id"]]) {
    $(listId).addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-memory-id]");
      if (!button) return;
      try { await api("/api/profile", { method: "POST", body: { [field]: button.dataset.memoryId } }); await fetchStatus(); }
      catch (error) { toast(error.message, true); }
    });
  }

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
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/@([A-Za-z0-9_-]+)/g, '<span class="skill-mention">@$1</span>');
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
    await ensureSession();
    const headers = new Headers(options.headers || {});
    if (localToken) headers.set("X-OmniVLA-Session", localToken);
    if (pairingToken) headers.set("X-OmniVLA-Pairing", pairingToken);
    const request = { cache: "no-store", ...options, headers };
    if (request.body !== undefined) {
      headers.set("Content-Type", "application/json");
      if (typeof request.body !== "string") request.body = JSON.stringify(request.body);
    }
    const response = await fetch(path, request);
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* empty response */ }
    if (response.status === 401) {
      if (isDesktopHost) localToken = "";
      else { pairingToken = ""; sessionStorage.removeItem("omnivla-pairing"); $("pairing-card").hidden = false; }
    }
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
      return `<div class="chat-row is-entering${active ? " is-active" : ""}" style="--item-index:${index}" data-chat-id="${escapeHtml(chat.id)}"><button class="chat-row-open" type="button"><span class="chat-row-title">${escapeHtml(chat.title || "New chat")}</span></button><button class="chat-row-delete" type="button" title="Delete chat" aria-label="Delete ${escapeHtml(chat.title || "chat")}">${icon("trash")}</button></div>`;
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
    if ($("delete-chat")) $("delete-chat").disabled = (data.chats || []).length <= 1 || chat.status === "running";
  }

  function extractPlanCardData(content) {
    const text = String(content || "").trim();
    const codeBlockMatch = text.match(/```(?:desktop-plan|plan)?\s*([\s\S]+?)```/i);
    let planSource = "";
    let preface = "";
    let outro = "";

    if (codeBlockMatch) {
      planSource = codeBlockMatch[1].trim();
      preface = text.slice(0, codeBlockMatch.index).trim();
      outro = text.slice(codeBlockMatch.index + codeBlockMatch[0].length).trim();
    } else {
      const hasKeywords = /(?:prescribed|estimated)\s*steps?|expected\s+(?:output|deliverable|result)/i.test(text);
      const actionMatches = text.match(/^\s*(?:[-*]\s*)?(?:step\s*)?\d+[.):]\s*(?:open|click|press|launch|navigate|type|switch|close|focus|select|scroll|drag|move|download|verify|inspect|start|run)\b/gim);
      if (hasKeywords || (actionMatches && actionMatches.length >= 2)) {
        const firstStepIdx = text.search(/^\s*(?:[-*]\s*)?(?:step\s*)?\d+[.):]\s+/m);
        if (firstStepIdx !== -1) {
          preface = text.slice(0, firstStepIdx).trim();
          planSource = text.slice(firstStepIdx).trim();
        }
      }
    }

    if (!planSource) return null;

    const stepLines = [];
    const outputLines = [];
    const criteriaLines = [];
    let prescribedSteps = 35;

    const budgetMatch = planSource.match(/(?:prescribed|estimated)\s*(?:step\s*budget|steps?)?\s*[:=]?\s*(\d+)/i);
    if (budgetMatch) {
      prescribedSteps = parseInt(budgetMatch[1], 10) || 35;
    }

    let section = "steps";
    for (const line of planSource.split("\n")) {
      const clean = line.trim();
      if (!clean) continue;
      if (/^\*{0,2}expected\s+(?:output|deliverable|result)\s*:?\*{0,2}\s*[:=]?/i.test(clean)) {
        section = "output";
        const remainder = clean.replace(/^\*{0,2}expected\s+(?:output|deliverable|result)\s*:?\*{0,2}\s*[:=]?\s*/i, "").trim();
        if (remainder) outputLines.push(remainder);
        continue;
      }
      if (/^\*{0,2}success\s+criteria\s*:?\*{0,2}\s*[:=]?/i.test(clean)) {
        section = "criteria";
        const remainder = clean.replace(/^\*{0,2}success\s+criteria\s*:?\*{0,2}\s*[:=]?\s*/i, "").trim();
        if (remainder) criteriaLines.push(remainder);
        continue;
      }
      if (/^(?:prescribed|estimated)\s*steps?\b/i.test(clean)) continue;

      if (section === "criteria" && /^(?:[-*]\s*(?:\[[ xX]\]\s*)?|\d+[.):]\s*)/.test(clean)) {
        criteriaLines.push(clean.replace(/^(?:[-*]\s*(?:\[[ xX]\]\s*)?|\d+[.):]\s*)/, "").trim());
        continue;
      }

      const stepMatch = clean.match(/^\s*(?:[-*]\s*)?(?:step\s*)?(\d+)[.):]\s*(.+?)$/i);
      if (stepMatch) {
        if (!codeBlockMatch && /^\[.+?\]\(https?:\/\//i.test(stepMatch[2].trim())) {
          return null;
        }
        section = "steps";
        stepLines.push(stepMatch[2].trim());
        continue;
      }

      if (section === "output") {
        outputLines.push(clean);
      } else if (section === "criteria" && criteriaLines.length) {
        criteriaLines[criteriaLines.length - 1] += " " + clean;
      } else if (stepLines.length > 0) {
        stepLines[stepLines.length - 1] += " " + clean;
      }
    }

    if (stepLines.length < 2) return null;

    return {
      preface,
      outro,
      steps: stepLines,
      expectedOutput: outputLines.join(" ").trim(),
      successCriteria: criteriaLines.slice(0, 5),
      prescribedSteps,
    };
  }

  function renderAssistantMessageBody(content, messageIndex, isLatest, contextRefs = [], completionEvidence = null) {
    const plan = extractPlanCardData(content);
    if (!plan) {
      const evidenceHtml = completionEvidence && ["visual", "operator", "inconclusive"].includes(completionEvidence.source) ? `
        <details class="completion-evidence">
          <summary>Completion check: ${escapeHtml(completionEvidence.source)}</summary>
          <p>${escapeHtml(completionEvidence.evidence || "No detailed evidence recorded.")}</p>
          ${Array.isArray(completionEvidence.criteria) && completionEvidence.criteria.length ? `<ul>${completionEvidence.criteria.map((check) =>
            `<li>${check.met ? "✓" : "○"} ${escapeHtml(check.evidence || "No visible evidence")}</li>`).join("")}</ul>` : ""}
        </details>` : "";
      return renderMarkdown(content) + evidenceHtml;
    }

    const prefaceHtml = plan.preface ? renderMarkdown(plan.preface) : "";
    const outroHtml = plan.outro ? renderMarkdown(plan.outro) : "";

    const stepsHtml = plan.steps.map((step, idx) => `
      <li class="plan-card-step-item">
        <span class="plan-card-step-num">${idx + 1}</span>
        <span class="plan-card-step-text">${inlineMarkdown(step)}</span>
      </li>
    `).join("");

    const outputHtml = plan.expectedOutput ? `
      <div class="plan-card-output">
        <strong>Expected Output:</strong>
        <span>${escapeHtml(plan.expectedOutput)}</span>
      </div>
    ` : "";
    const contextHtml = Array.isArray(contextRefs) && contextRefs.length ? `
      <details class="plan-context">
        <summary>Personal context supplied to the planner (${contextRefs.length})</summary>
        <ul>${contextRefs.map((ref) => `
          <li><span>${escapeHtml(ref.label || "")}</span><small>${escapeHtml(ref.source || "")}</small></li>
        `).join("")}</ul>
      </details>
    ` : "";
    const criteriaHtml = plan.successCriteria.length ? `
      <div class="plan-card-criteria"><strong>Success criteria</strong><ul>
        ${plan.successCriteria.map((criterion) => `<li>${escapeHtml(criterion)}</li>`).join("")}
      </ul></div>
    ` : "";

    const cardHtml = `
      <div class="message-plan-card">
        <div class="plan-card-header">
          <div class="plan-card-title-group">
            <span class="plan-card-icon"><svg><use href="#i-terminal" /></svg></span>
            <strong>Proposed Action Plan</strong>
          </div>
          <span class="plan-card-budget">Planner budget: ${plan.prescribedSteps} steps</span>
        </div>
        <div class="plan-card-body">
          <ol class="plan-card-steps">
            ${stepsHtml}
          </ol>
          ${outputHtml}
          ${criteriaHtml}
          ${contextHtml}
        </div>
        <div class="plan-card-footer">
          <button class="plan-card-execute" data-plan-index="${messageIndex}" data-execute="true" type="button">
            <svg><use href="#i-play" /></svg>
            <span>Execute Plan</span>
          </button>
        </div>
      </div>
    `;

    return `${prefaceHtml}${cardHtml}${outroHtml}`;
  }

  function renderConversation(data) {
    const history = Array.isArray(data.chat_history) ? data.chat_history : [];
    const planning = data.planning_chat_id === data.active_chat_id;
    const activity = data.planner_activity || "Thinking...";
    const signature = JSON.stringify([data.active_chat_id, history, planning, activity, data.recovery]);
    if (state.renderSignatures.conversation === signature) return;
    const scroller = $("chat-scroll");
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
    const previousChat = state.renderSignatures.conversationChat;
    state.renderSignatures.conversation = signature;
    state.renderSignatures.conversationChat = data.active_chat_id;
    $("chat-empty").hidden = history.some((message) => message.role === "user") || planning;

    let latestPlanIndex = -1;
    history.forEach((msg, idx) => {
      if (msg.role === "assistant" && extractPlanCardData(msg.content)) {
        latestPlanIndex = idx;
      }
    });

    const messages = history.map((message, messageIndex) => {
      const role = message.role === "user" ? "user" : "assistant";
      const isLatest = messageIndex === latestPlanIndex;
      const bodyHtml = role === "assistant"
        ? renderAssistantMessageBody(message.content, messageIndex, isLatest, message.context_refs, message.completion_evidence)
        : renderMarkdown(message.content);
      return `<article class="message is-${role}"><div class="message-avatar" aria-hidden="true">${role === "user" ? "You" : "O"}</div><div class="message-body">${bodyHtml}</div></article>`;
    });
    if (data.recovery && Array.isArray(data.recovery.actions)) {
      const actions = data.recovery.actions.map(item =>
        `<li>${escapeHtml(item.label || item.action || "Action")} <small>${item.dispatched ? "Input dispatched; effect uncertain" : "Not confirmed"}</small></li>`
      ).join("");
      messages.unshift(`<section class="recovery-card"><strong>Recovery checkpoint</strong><p>The previous run ${escapeHtml(data.recovery.prior_status || "stopped")}. These recorded inputs are not proof of the result; the new plan must inspect the current state.</p>${actions ? `<details><summary>Recorded inputs</summary><ul>${actions}</ul></details>` : "<p>No input checkpoint was recorded.</p>"}</section>`);
    }
    if (planning) {
      const isSearch = /search|browse|web/i.test(activity);
      const isRead = /read|page|article/i.test(activity);
      const isFile = /file|find|local/i.test(activity);
      const isSynth = /synth|answer|prose/i.test(activity);
      let iconBadge = '<span class="thinking-pulse-dot" aria-hidden="true"></span>';
      if (isSearch) {
        iconBadge = `<span class="thinking-badge-icon">${icon("search")}</span>`;
      } else if (isRead || isFile) {
        iconBadge = `<span class="thinking-badge-icon">${icon("file")}</span>`;
      } else if (isSynth) {
        iconBadge = `<span class="thinking-badge-icon">${icon("spark")}</span>`;
      }
      messages.push(`
        <article class="message is-assistant is-pending">
          <div class="message-avatar" aria-hidden="true">O</div>
          <div class="message-body message-thinking">
            <div class="thinking-progress-pill" aria-live="polite">
              ${iconBadge}
              <span class="thinking-label">${escapeHtml(activity)}</span>
              <span class="thinking-shimmer" aria-hidden="true"></span>
            </div>
            <div class="message-skeleton" aria-hidden="true">
              <span></span><span></span><span></span>
            </div>
          </div>
        </article>
      `);
    }
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

    const needsInput = (phase === "hitl" || Boolean(data.hitl_question)) && activeSelected;
    $("operator-request").hidden = !needsInput;
    if (needsInput) $("operator-question").textContent = data.hitl_question || data.current_action || "Please review the current screen.";

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
    const live = data?.execution_live || {};
    const isHitl = live.phase === "hitl" || live.status === "hitl" || data?.phase === "hitl" || Boolean(data?.hitl_question || live.hitl_question);
    const activeSelected = isSelectedExecution(data);
    const hasText = Boolean($("composer-input").value.trim());

    if (isHitl) {
      $("send-message").disabled = true;
      $("composer-input").disabled = true;
      $("composer-input").placeholder = "Respond using the review card";
      $("composer-hint").textContent = "Your response applies only to the pending action.";
      return;
    }

    const blocked = isLiveWorking(data) || data.planning_chat_id === data.active_chat_id;
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
    if ($("local-state-label")) $("local-state-label").textContent = ready ? "Ready" : "Starting";
    if ($("local-state-dot")) $("local-state-dot").dataset.state = ready ? "ready" : "starting";
    if ($("settings-service-label")) $("settings-service-label").textContent = ready ? "Ready for tasks" : "Getting ready";
    if ($("settings-service-dot")) $("settings-service-dot").dataset.state = ready ? "ready" : "starting";
  }


  function renderProfileFacts(facts) {
    const list = $("profile-facts-list");
    if (!list) return;
    if (!facts || facts.length === 0) {
      list.innerHTML = `<li class="panel-empty" style="padding: 4px 0;">No learned rules yet.</li>`;
      return;
    }
    list.innerHTML = facts.map((fact, idx) => `
      <li class="profile-fact-item">
        <span>${escapeHtml(fact)}</span>
        <button type="button" class="profile-fact-del" data-fact-index="${idx}" aria-label="Delete rule">
          <svg><use href="#i-close" /></svg>
        </button>
      </li>
    `).join("");
    list.querySelectorAll(".profile-fact-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const index = Number(btn.dataset.factIndex);
        try {
          const res = await api("/api/profile", { method: "POST", body: { delete_fact_index: index } });
          if (res?.profile?.facts) renderProfileFacts(res.profile.facts);
          toast("Rule removed from memory.");
        } catch (err) { toast(err.message, true); }
      });
    });
  }

  async function addProfileFact() {
    const input = $("new-fact-input");
    const val = input ? input.value.trim() : "";
    if (!val) return;
    try {
      const res = await api("/api/profile", { method: "POST", body: { fact: val } });
      input.value = "";
      if (res?.profile?.facts) renderProfileFacts(res.profile.facts);
      toast("Learned rule added to memory.");
    } catch (err) { toast(err.message, true); }
  }

  function renderSettings(data) {
    const signature = JSON.stringify([data.settings, data.safety, data.user_profile]);
    if (state.settingsSignature === signature || $("settings-form").contains(document.activeElement)) return;
    state.settingsSignature = signature;
    $("memory-enabled").checked = Boolean(data.settings?.memory_enabled);
    $("enable-recording").checked = Boolean(data.settings?.enable_recording);
    $("safety-mode").value = data.safety?.mode || "supervised";
    $("require-plan-approval").checked = data.safety?.require_plan_approval !== false;

    const profile = data.user_profile || {};
    const emailPref = profile.preferences?.email || {};
    const browserPref = profile.preferences?.browser || {};
    if ($("pref-email-account")) $("pref-email-account").value = emailPref.account || "";
    if ($("pref-email-service")) $("pref-email-service").value = emailPref.service || "";
    if ($("pref-browser")) $("pref-browser").value = browserPref.default || "";
    renderProfileFacts(profile.facts || []);
    $("personal-learning").checked = profile.learning_enabled !== false;
    $("remote-control").checked = Boolean(data.safety?.remote_control_enabled);
    $("pairing-settings").hidden = data.access?.is_local === false;
    const entities = Array.isArray(profile.entities) ? profile.entities : [];
    const relations = Array.isArray(profile.relations) ? profile.relations : [];
    $("memory-summary").textContent = `${(profile.memories || []).length} personal records · ${entities.length} linked people, projects, or documents · ${(profile.workflows || []).length} successful workflows`;
    const names = new Map(entities.map(entity => [entity.id, entity.name]));
    const memoryItem = (label, source, id) => {
      const item = document.createElement("li");
      item.className = "memory-map-item";
      const copy = document.createElement("span");
      copy.textContent = `${label} — Source: ${source || "user-confirmed"}`;
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "secondary-button";
      remove.dataset.memoryId = id; remove.textContent = "Forget";
      remove.setAttribute("aria-label", `Forget ${label}`);
      item.append(copy, remove);
      return item;
    };
    $("memory-entities").replaceChildren(...entities.slice(-30).map(entity =>
      memoryItem(`${entity.kind}: ${entity.name}`, entity.source, entity.id)));
    $("memory-relations").replaceChildren(...relations.slice(-30).map(relation =>
      memoryItem(`${names.get(relation.subject_id) || "Unknown"} → ${relation.predicate} → ${names.get(relation.object_id) || "Unknown"}`, relation.source, relation.id)));
    $("memory-provenance").replaceChildren(...(profile.memories || []).slice(-20).reverse().map(record => {
      return memoryItem(`${record.key}: ${record.value}`, record.source, record.id);
    }));
  }

  function updateExecutionVisibility(data) {
    const activeSelected = isSelectedExecution(data) && isLiveWorking(data);
    const chat = (data.chats || []).find((item) => item.id === data.active_chat_id) || {};
    const chatWorking = ["running", "executing", "working", "hitl"].includes(chat.status);
    const isExecuting = activeSelected || chatWorking;
    const isHitl = data?.phase === "hitl" || Boolean(data?.hitl_question) || data?.execution_live?.phase === "hitl";

    const hasPlan = Boolean(data.active_plan);
    const hasExecutableTask = hasPlan || isExecuting;

    document.body.classList.toggle("has-executable-task", hasExecutableTask);
    document.body.classList.toggle("is-executing", isExecuting);

    if (isExecuting || isHitl) {
      document.body.classList.remove("execution-closed");
    } else if (!hasExecutableTask) {
      document.body.classList.add("execution-closed");
    }

    const toggleBtn = $("toggle-execution");
    if (toggleBtn) {
      const isClosed = document.body.classList.contains("execution-closed");
      toggleBtn.setAttribute("aria-expanded", String(!isClosed));
    }
  }

  function renderStatus(data) {
    state.status = data;
    document.body.dataset.executionTone = phaseTone(data.phase || data.status);
    updateExecutionVisibility(data);
    renderSidebar(data);
    renderHeader(data);
    renderConversation(data);
    renderExecution(data);
    renderComposer(data);
    renderLocalState(data);
    renderSettings(data);
    renderIntervention(data);
  }

  async function fetchStatus() {
    if (state.requestInFlight) return;
    state.requestInFlight = true;
    try {
      renderStatus(await api("/api/status"));
    } catch (error) {
      if ($("local-state-label")) $("local-state-label").textContent = "Unavailable";
      if ($("local-state-dot")) $("local-state-dot").dataset.state = "error";
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
    if (!message) return;

    const live = state.status?.execution_live || {};
    const isHitl = live.phase === "hitl" || live.status === "hitl" || state.status?.phase === "hitl" || Boolean(state.status?.hitl_question || live.hitl_question);
    if (isHitl && isSelectedExecution(state.status)) {
      setBusy($("send-message"), true, "Sending");
      try {
        await api("/api/hitl_submit", { method: "POST", body: { ...state.status?.intervention, response: message } });
        input.value = "";
        resizeComposer();
        toast("Response submitted to agent.");
        await fetchStatus();
      } catch (error) {
        toast(error.message, true);
      } finally {
        setBusy($("send-message"), false);
        renderComposer(state.status || {});
      }
      return;
    }

    if (isLiveWorking(state.status)) return;
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
    const existingDraft = (state.status?.chats || []).find(
      (c) => (!c.chat_history || c.chat_history.length === 0) && !c.intent && c.status === "draft"
    );
    if (existingDraft) {
      return switchChat(existingDraft.id);
    }
    try {
      await api("/api/chats/new", { method: "POST", body: {} });
      state.currentScreen = null;
      state.renderSignatures = {};
      document.body.classList.remove("has-executable-task", "is-executing");
      document.body.classList.add("execution-closed");
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

  async function selectPlan(messageIndex, executeNow = false) {
    const plan = state.status?.chat_history?.[Number(messageIndex)]?.content;
    if (!plan) return;
    try {
      const res = await api("/api/plans/select", {
        method: "POST",
        body: { chat_id: state.status.active_chat_id, plan, message_index: Number(messageIndex) }
      });
      state.renderSignatures = {};
      if (res?.plan && state.status) {
        state.status.active_plan = res.plan;
      }
      await fetchStatus();
      if (executeNow) {
        document.body.classList.remove("execution-closed");
        if ($("risk-ack")) $("risk-ack").checked = true;
        await runPlan();
      } else {
        document.body.classList.remove("execution-closed");
        toast("Plan selected for review.");
      }
    } catch (error) { toast(error.message, true); }
  }

  function handleComposerAutocomplete() {
    const input = $("composer-input");
    if (!input) return;
    const val = input.value;
    const cursorPos = input.selectionStart;
    const textBeforeCursor = val.slice(0, cursorPos);
    const atMatch = textBeforeCursor.match(/@([a-zA-Z0-9_-]*)$/);

    if (!atMatch || !state.skills || state.skills.length === 0) {
      closeAutocomplete();
      return;
    }

    const query = atMatch[1].toLowerCase();
    state.autocomplete.triggerPos = atMatch.index;
    state.autocomplete.query = query;
    const matches = state.skills.filter((s) =>
      s.name.toLowerCase().includes(query) || (s.title && s.title.toLowerCase().includes(query))
    );

    if (matches.length === 0) {
      closeAutocomplete();
      return;
    }

    state.autocomplete.open = true;
    state.autocomplete.matches = matches;
    state.autocomplete.selectedIndex = Math.min(state.autocomplete.selectedIndex, matches.length - 1);
    renderAutocomplete();
  }

  function closeAutocomplete() {
    state.autocomplete.open = false;
    state.autocomplete.selectedIndex = 0;
    const el = $("skill-autocomplete");
    if (el) el.hidden = true;
  }

  function renderAutocomplete() {
    const el = $("skill-autocomplete");
    if (!el || !state.autocomplete.open) return;
    el.hidden = false;
    el.innerHTML = state.autocomplete.matches.map((skill, index) => {
      const isSelected = index === state.autocomplete.selectedIndex;
      return `
        <div class="skill-autocomplete-item${isSelected ? " is-selected" : ""}" data-skill-index="${index}">
          <div class="skill-autocomplete-left">
            <strong class="skill-autocomplete-title">${escapeHtml(skill.title || skill.name)}</strong>
            <span class="skill-autocomplete-desc">${escapeHtml(skill.description || "")}</span>
          </div>
          <span class="skill-autocomplete-tag">@${escapeHtml(skill.name)}</span>
        </div>
      `;
    }).join("");
  }

  function insertAutocompleteSkill(index) {
    const skill = state.autocomplete.matches[index];
    if (!skill) return;
    const input = $("composer-input");
    const val = input.value;
    const prefix = val.slice(0, state.autocomplete.triggerPos);
    const suffix = val.slice(input.selectionStart);
    const inserted = `@${skill.name} `;
    input.value = prefix + inserted + suffix;
    input.selectionStart = input.selectionEnd = prefix.length + inserted.length;
    closeAutocomplete();
    input.focus();
    resizeComposer();
  }

  async function retryChat() {
    try {
      const result = await api("/api/chats/retry", { method: "POST", body: {} });
      state.renderSignatures = {};
      await fetchStatus();
      toast(result?.message ? "Preparing a recovery plan..." : "Retry ready for review.");
    } catch (error) { toast(error.message, true); }
  }

  async function runPlan() {
    let plan = state.status?.active_plan;
    if (!plan) {
      await fetchStatus();
      plan = state.status?.active_plan;
    }
    if (!plan) {
      toast("No active plan to run. Please select or prepare a plan first.", true);
      return;
    }
    const highRisk = Boolean(plan.risk?.requires_explicit_acknowledgement);
    if (highRisk && !$("risk-ack")?.checked) {
      document.body.classList.remove("execution-closed");
      $("risk-ack")?.focus();
      toast("Please acknowledge task permissions in the panel to start.", true);
      return;
    }
    setBusy($("run-plan"), true, "Starting");
    try {
      await api("/api/confirm", { method: "POST", body: {
        task: plan.execution_task || plan.plan,
        source_task: plan.source_task,
        approved: true,
        risk_acknowledged: !highRisk || Boolean($("risk-ack")?.checked),
        chat_id: state.status?.active_chat_id,
      } });
      document.body.classList.remove("execution-closed");
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

  function insertSkillInChat(skillName) {
    if (!skillName) return;
    openWorkspace("chat");
    const input = $("composer-input");
    if (!input) return;
    const tag = `@${skillName} `;
    if (!input.value.includes(tag)) {
      input.value = `${tag}${input.value}`.trimStart();
    }
    resizeComposer();
    input.focus();
    toast(`Inserted @${skillName} into composer.`);
  }

  async function deleteNamedSkill(skillName) {
    if (!skillName || !window.confirm(`Delete skill “${skillName}”?`)) return;
    try {
      await api("/api/skills/delete", { method: "POST", body: { name: skillName } });
      if (state.editingSkill === skillName) {
        state.editingSkill = null;
      }
      await loadSkills();
      toast("Skill deleted.");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function insertSnippet(text) {
    const textarea = $("skill-markdown");
    if (!textarea) return;
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || 0;
    const before = textarea.value.substring(0, start);
    const after = textarea.value.substring(end);
    textarea.value = before + text + after;
    textarea.selectionStart = textarea.selectionEnd = start + text.length;
    textarea.focus();
  }

  function renderSkills() {
    const query = ($("skill-search")?.value || "").trim().toLowerCase();
    const filter = state.skillDomainFilter || "all";

    const filtered = (state.skills || []).filter((skill) => {
      const text = [skill.name, skill.title, skill.description, ...(skill.tags || [])].join(" ").toLowerCase();
      const matchesQuery = !query || text.includes(query);
      const matchesFilter = filter === "all" || (skill.domain || "general").toLowerCase() === filter.toLowerCase();
      return matchesQuery && matchesFilter;
    });

    const badge = $("skill-count-badge");
    if (badge) {
      badge.textContent = `${filtered.length} ${filtered.length === 1 ? "skill" : "skills"}`;
    }

    const listEl = $("skill-list");
    if (!listEl) return;

    if (!filtered.length) {
      listEl.innerHTML = `<div class="utility-empty"><span class="empty-mark"><i></i><i></i></span><h2>${query || filter !== "all" ? "No matching skills" : "No skills yet"}</h2><p>${query || filter !== "all" ? "Try another search or filter." : "Create one with the Intelligent Studio or Markdown editor."}</p></div>`;
      return;
    }

    listEl.innerHTML = filtered.map((skill) => {
      const triggers = Array.isArray(skill.triggers) ? skill.triggers : [];
      const triggersHtml = triggers.slice(0, 3).map((t) => `<span class="intel-chip intel-chip-trigger">${escapeHtml(t)}</span>`).join("");
      const extraTriggers = triggers.length > 3 ? `<span class="intel-chip-empty">+${triggers.length - 3} more</span>` : "";

      return `
        <div class="skill-card" data-skill-name="${escapeHtml(skill.name)}">
          <div class="skill-card-top">
            <div class="skill-card-title-wrap">
              <h3 class="skill-card-title">${escapeHtml(skill.title || skill.name)}</h3>
              <span class="skill-card-slug">@${escapeHtml(skill.name)}</span>
            </div>
            <span class="intel-pill intel-pill-domain">${escapeHtml(skill.domain || "general")}</span>
          </div>
          <p class="skill-card-desc">${escapeHtml(skill.description || "No description provided.")}</p>
          ${triggersHtml ? `<div class="skill-card-triggers">${triggersHtml}${extraTriggers}</div>` : ""}
          <div class="skill-card-bottom">
            <div class="skill-card-actions">
              <button class="primary-button" data-skill-action="use" type="button" title="Use @${escapeHtml(skill.name)} in chat">
                <svg><use href="#i-chat" /></svg>
                <span>Use</span>
              </button>
              <button class="secondary-button" data-skill-action="edit" type="button" title="Edit in Markdown">
                <svg><use href="#i-file" /></svg>
                <span>Edit</span>
              </button>
            </div>
            <button class="danger-text" data-skill-action="delete" type="button" title="Delete skill">
              <svg><use href="#i-trash" /></svg>
            </button>
          </div>
        </div>
      `;
    }).join("");
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

  function renderIntelligentSkillPreview(skill) {
    if (!skill) return;
    state.latestIntelligentSkill = skill;
    const placeholder = $("intel-preview-placeholder");
    const card = $("intel-preview-card");
    if (placeholder) placeholder.hidden = true;
    if (card) card.hidden = false;

    if ($("preview-skill-title")) $("preview-skill-title").textContent = skill.title || skill.name;
    if ($("preview-skill-slug")) $("preview-skill-slug").textContent = `@${skill.name}`;
    if ($("preview-skill-domain")) $("preview-skill-domain").textContent = skill.domain || "general";
    if ($("preview-skill-desc")) $("preview-skill-desc").textContent = skill.description || "Synthesized procedural skill for Holo 3.1.";

    // Triggers
    const triggers = Array.isArray(skill.triggers) ? skill.triggers : [];
    if ($("preview-triggers")) {
      $("preview-triggers").innerHTML = triggers.length
        ? triggers.map((t) => `<span class="intel-chip intel-chip-trigger">${escapeHtml(t)}</span>`).join("")
        : `<span class="intel-chip-empty">No trigger phrases</span>`;
    }

    // Parameters
    const params = Array.isArray(skill.parameters) ? skill.parameters : [];
    if ($("preview-parameters")) {
      $("preview-parameters").innerHTML = params.length
        ? params.map((p) => `<span class="intel-chip intel-chip-param"><strong>${escapeHtml(p.name || "param")}</strong>: ${escapeHtml(p.description || p.type || "value")}${p.required ? " (required)" : ""}</span>`).join("")
        : `<span class="intel-chip-empty">No dynamic parameters</span>`;
    }

    // Strategy & Visual Grounding
    const strategy = [
      skill.strategy ? `### Cognitive Strategy\n${skill.strategy}` : "",
      skill.visual_landmarks ? `### Visual Landmarks\n${skill.visual_landmarks}` : "",
      skill.failure_recovery ? `### Failure Recovery\n${skill.failure_recovery}` : ""
    ].filter(Boolean).join("\n\n") || skill.raw_markdown || "";

    if ($("preview-strategy")) {
      $("preview-strategy").innerHTML = strategy
        ? `<pre class="intel-strategy-text">${escapeHtml(strategy.trim())}</pre>`
        : `<p class="intel-chip-empty">Standard procedural guidance generated.</p>`;
    }
  }

  async function generateIntelligentSkill(event) {
    if (event) event.preventDefault();
    const goal = $("intel-goal")?.value.trim();
    if (!goal) {
      toast("Please enter a task goal.", true);
      $("intel-goal")?.focus();
      return;
    }

    const domain = $("intel-domain")?.value || "general";
    const name = $("intel-name")?.value.trim() || undefined;
    const captureScreen = $("intel-screen") ? $("intel-screen").checked : true;
    const notes = $("intel-notes")?.value.trim() || undefined;

    const generateBtn = $("generate-intel-skill");
    const spinner = $("intel-spinner");
    const spinnerText = $("intel-spinner-text");

    if (generateBtn) generateBtn.disabled = true;
    if (spinner) spinner.hidden = false;
    if (spinnerText) {
      spinnerText.textContent = captureScreen
        ? "Grounding with screen landmarks & synthesizing procedural skill…"
        : "Synthesizing procedural skill with Qwen…";
    }

    try {
      const result = await api("/api/skills/generate_intelligent", {
        method: "POST",
        body: {
          goal,
          domain,
          name,
          capture_screen: captureScreen,
          notes,
        },
      });

      if (result.skill) {
        renderIntelligentSkillPreview(result.skill);
        await loadSkills();
        toast(`Skill @${result.skill.name} synthesized and saved!`);
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (generateBtn) generateBtn.disabled = false;
      if (spinner) spinner.hidden = true;
    }
  }

  function useIntelligentSkillInChat() {
    const skill = state.latestIntelligentSkill;
    if (!skill) return;
    openWorkspace("chat");
    const input = $("composer-input");
    if (!input) return;
    const tag = `@${skill.name} `;
    if (!input.value.includes(tag)) {
      input.value = `${tag}${input.value}`.trimStart();
    }
    resizeComposer();
    input.focus();
    toast(`Inserted @${skill.name} into composer.`);
  }

  function editIntelligentSkillMarkdown() {
    const skill = state.latestIntelligentSkill;
    if (!skill) return;
    const existing = state.skills.find((s) => s.name === skill.name);
    startSkillEditor(existing || skill);
  }

  async function saveSettings(event) {
    event.preventDefault();
    $("settings-save-state").textContent = "Saving…";
    try {
      await api("/api/settings", { method: "POST", body: {
        memory_enabled: $("memory-enabled").checked,
        enable_recording: $("enable-recording").checked,
      } });
      await api("/api/safety", { method: "POST", body: {
        mode: $("safety-mode").value,
        require_plan_approval: $("require-plan-approval").checked,
        remote_control_enabled: $("remote-control").checked,
      } });
      if ($("pref-email-account")) {
        await api("/api/profile", { method: "POST", body: {
          preference: { category: "email", key: "account", value: $("pref-email-account").value.trim() }
        } });
      }
      if ($("pref-email-service")) {
        await api("/api/profile", { method: "POST", body: {
          preference: { category: "email", key: "service", value: $("pref-email-service").value }
        } });
      }
      if ($("pref-browser")) {
        await api("/api/profile", { method: "POST", body: {
          preference: { category: "browser", key: "default", value: $("pref-browser").value.trim() }
        } });
      }
      await api("/api/profile", { method: "POST", body: { learning_enabled: $("personal-learning").checked } });
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
    $("quit-app")?.addEventListener("click", quitApplication);
    $("new-chat")?.addEventListener("click", createChat);
    $("chat-search")?.addEventListener("input", () => state.status && renderSidebar(state.status));
    $("chat-list")?.addEventListener("click", (event) => {
      const row = event.target.closest("[data-chat-id]");
      if (!row) return;
      if (event.target.closest(".chat-row-delete")) {
        event.stopPropagation();
        deleteChat(row.dataset.chatId);
      } else if (event.target.closest(".chat-row-open")) {
        switchChat(row.dataset.chatId);
      }
    });
    $("menu-delete-chat")?.addEventListener("click", () => { const id = state.menuChatId; if ($("chat-menu")) $("chat-menu").hidden = true; state.menuChatId = null; if (id) deleteChat(id); });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".chat-row-delete") && !event.target.closest("#chat-menu")) { if ($("chat-menu")) $("chat-menu").hidden = true; state.menuChatId = null; }
      if (!event.target.closest(".composer-wrap")) closeAutocomplete();
    });
    $("conversation")?.addEventListener("click", (event) => {
      const choice = event.target.closest("[data-plan-index]");
      if (choice) {
        const executeNow = choice.dataset.execute === "true";
        selectPlan(choice.dataset.planIndex, executeNow);
      }
    });
    $("open-sidebar")?.addEventListener("click", () => { document.body.classList.add("sidebar-open"); if ($("sidebar-scrim")) $("sidebar-scrim").hidden = false; });
    $("close-sidebar")?.addEventListener("click", closeMobileSidebar);
    $("sidebar-scrim")?.addEventListener("click", closeMobileSidebar);
    $("open-skills")?.addEventListener("click", () => openWorkspace("skills"));
    $("open-settings")?.addEventListener("click", () => openWorkspace("settings"));
    document.querySelectorAll(".back-to-chat").forEach((button) => button.addEventListener("click", () => openWorkspace("chat")));

    $("composer-form")?.addEventListener("submit", (event) => { event.preventDefault(); sendMessage(); });
    $("composer-input")?.addEventListener("input", () => {
      resizeComposer();
      handleComposerAutocomplete();
    });
    $("composer-input")?.addEventListener("keydown", (event) => {
      if (state.autocomplete?.open) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          state.autocomplete.selectedIndex = (state.autocomplete.selectedIndex + 1) % state.autocomplete.matches.length;
          renderAutocomplete();
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          state.autocomplete.selectedIndex = (state.autocomplete.selectedIndex - 1 + state.autocomplete.matches.length) % state.autocomplete.matches.length;
          renderAutocomplete();
          return;
        }
        if (event.key === "Enter" || event.key === "Tab") {
          event.preventDefault();
          insertAutocompleteSkill(state.autocomplete.selectedIndex);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          closeAutocomplete();
          return;
        }
      }
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMessage();
      }
    });
    $("skill-autocomplete")?.addEventListener("click", (event) => {
      const item = event.target.closest("[data-skill-index]");
      if (item) insertAutocompleteSkill(Number(item.dataset.skillIndex));
    });
    $("chat-empty")?.addEventListener("click", (event) => {
      const card = event.target.closest("[data-suggestion]");
      if (card && $("composer-input")) {
        $("composer-input").value = card.dataset.suggestion;
        resizeComposer();
        $("composer-input").focus();
      }
    });
    document.querySelectorAll("[data-suggestion]").forEach((button) => button.addEventListener("click", () => { if ($("composer-input")) { $("composer-input").value = button.dataset.suggestion; resizeComposer(); $("composer-input").focus(); } }));

    $("toggle-execution")?.addEventListener("click", () => {
      document.body.classList.toggle("execution-closed");
      const isClosed = document.body.classList.contains("execution-closed");
      $("toggle-execution")?.setAttribute("aria-expanded", String(!isClosed));
    });
    $("close-execution")?.addEventListener("click", () => {
      document.body.classList.add("execution-closed");
      $("toggle-execution")?.setAttribute("aria-expanded", "false");
    });
    $("delete-chat")?.addEventListener("click", () => deleteChat());
    $("retry-chat")?.addEventListener("click", retryChat);
    $("risk-ack")?.addEventListener("change", () => { state.renderSignatures.execution = null; if (state.status) renderExecution(state.status); });
    $("run-plan")?.addEventListener("click", runPlan);
    $("add-fact-btn")?.addEventListener("click", addProfileFact);
    $("new-fact-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addProfileFact();
      }
    });
    $("pause-run")?.addEventListener("click", togglePause);
    $("stop-run")?.addEventListener("click", stopRun);
    $("operator-form")?.addEventListener("submit", async (event) => {
      event.preventDefault(); const response = $("operator-input")?.value.trim(); if (!response) return;
      try { await api("/api/hitl_submit", { method: "POST", body: { response } }); if ($("operator-input")) $("operator-input").value = ""; await fetchStatus(); }
      catch (error) { toast(error.message, true); }
    });

    document.querySelectorAll("[data-skill-tab]").forEach((button) => button.addEventListener("click", () => openSkillTab(button.dataset.skillTab)));
    $("new-skill")?.addEventListener("click", () => startSkillEditor());
    $("skill-search")?.addEventListener("input", renderSkills);
    $("library-filters")?.addEventListener("click", (event) => {
      const chip = event.target.closest(".filter-chip");
      if (!chip) return;
      document.querySelectorAll(".library-filter-chips .filter-chip").forEach((c) => c.classList.remove("is-active"));
      chip.classList.add("is-active");
      state.skillDomainFilter = chip.dataset.filter || "all";
      renderSkills();
    });
    $("skill-list")?.addEventListener("click", (event) => {
      const card = event.target.closest("[data-skill-name]");
      if (!card) return;
      const skillName = card.dataset.skillName;
      const skill = state.skills.find((s) => s.name === skillName);
      const actionBtn = event.target.closest("[data-skill-action]");
      const action = actionBtn ? actionBtn.dataset.skillAction : "open";
      if (action === "use") {
        insertSkillInChat(skillName);
      } else if (action === "delete") {
        deleteNamedSkill(skillName);
      } else {
        startSkillEditor(skill);
      }
    });
    $("insert-frontmatter-snippet")?.addEventListener("click", () => {
      insertSnippet(`---
name: custom_task
title: Custom Task Workflow
description: Automates a specific desktop workflow
domain: productivity
triggers:
  - run custom task
  - execute custom workflow
parameters:
  - name: target_item
    type: string
    description: Item or text to target
    required: true
---

`);
    });
    $("insert-step-snippet")?.addEventListener("click", () => {
      insertSnippet(`
### Step N: Action Name
- **Visual Target:** Search bar or primary action button
- **Action:** Click or type {{target_item}}
`);
    });
    $("insert-recovery-snippet")?.addEventListener("click", () => {
      insertSnippet(`
### Failure Recovery Heuristics
- If the application window is minimized, bring it to the foreground.
- If a dialog or overlay blocks the view, dismiss or confirm it.
`);
    });
    $("skill-editor")?.addEventListener("submit", (event) => { event.preventDefault(); saveSkill(); });
    $("reset-skill")?.addEventListener("click", () => { if ($("skill-markdown")) $("skill-markdown").value = SKILL_TEMPLATE; state.editingSkill = null; if ($("delete-skill")) $("delete-skill").hidden = true; });
    $("delete-skill")?.addEventListener("click", deleteSkill);
    $("skill-file")?.addEventListener("change", (event) => importSkillFile(event.target.files[0]));
    ["dragenter", "dragover"].forEach((name) => $("import-zone")?.addEventListener(name, (event) => { event.preventDefault(); $("import-zone")?.classList.add("is-dragging"); }));
    ["dragleave", "drop"].forEach((name) => $("import-zone")?.addEventListener(name, (event) => { event.preventDefault(); $("import-zone")?.classList.remove("is-dragging"); if (name === "drop") importSkillFile(event.dataTransfer.files[0]); }));
    $("intel-skill-form")?.addEventListener("submit", generateIntelligentSkill);
    $("edit-intel-markdown")?.addEventListener("click", editIntelligentSkillMarkdown);
    $("use-intel-in-chat")?.addEventListener("click", useIntelligentSkillInChat);
    $("intel-open-lib")?.addEventListener("click", () => openSkillTab("library"));

    $("settings-form")?.addEventListener("submit", saveSettings);
    $("clear-memory")?.addEventListener("click", async () => {
      if (!window.confirm("Clear locally stored conversation recall? Chat history will remain.")) return;
      try { const result = await api("/api/memory/clear", { method: "POST", body: {} }); toast(`Cleared ${result.stores_cleared} local stores.`); }
      catch (error) { toast(error.message, true); }
    });
    $("restart-models")?.addEventListener("click", async () => {
      try { await api("/api/clear_vram", { method: "POST", body: {} }); toast("OmniVLA is restarting."); }
      catch (error) { toast(error.message, true); }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "n") { event.preventDefault(); createChat(); }
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "e") {
        event.preventDefault();
        document.body.classList.toggle("execution-closed");
        const isClosed = document.body.classList.contains("execution-closed");
        $("toggle-execution")?.setAttribute("aria-expanded", String(!isClosed));
      }
      if (event.key === "Escape" && isSelectedExecution(state.status) && isLiveWorking(state.status)) stopRun();
    });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { window.clearTimeout(state.pollTimer); fetchStatus(); } });
  }

  async function init() {
    if (window.matchMedia("(max-width: 900px)").matches) document.body.classList.add("execution-closed");
    bindEvents();
    resizeComposer();
    loadSkills();
    await fetchStatus();
    fetchScreen();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  init();
})();

---
name: OmniVLA
description: A quiet native workbench that keeps intent, plan, and live execution legible.
colors:
  sidebar: "#191918"
  sidebar-hover: "#292927"
  sidebar-active: "#333330"
  canvas: "#fbfbfa"
  surface: "#f5f5f3"
  surface-strong: "#ededeb"
  paper: "#ffffff"
  ink: "#1f1f1d"
  muted: "#6f6f6b"
  faint: "#989892"
  line: "#e5e5e1"
  line-strong: "#d4d4cf"
  focus: "#3974d8"
  success: "#2f7a49"
  success-soft: "#eaf4ed"
  attention: "#a34f24"
  attention-soft: "#fff1e8"
  danger: "#b13a35"
  danger-soft: "#fceceb"
typography:
  headline:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Inter, system-ui, sans-serif'
    fontSize: "clamp(24px, 3vw, 32px)"
    fontWeight: 610
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  title:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Inter, system-ui, sans-serif'
    fontSize: "14px"
    fontWeight: 620
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  body:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Inter, system-ui, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"Segoe UI Variable Text", "Segoe UI", Inter, system-ui, sans-serif'
    fontSize: "11px"
    fontWeight: 550
    lineHeight: 1.45
  mono:
    fontFamily: '"Cascadia Mono", Consolas, monospace'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  compact: "7px"
  control: "8px"
  surface: "12px"
  composer: "13px"
spacing:
  micro: "4px"
  control: "8px"
  compact: "10px"
  section: "16px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 13px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 13px"
    height: "40px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 10px"
    height: "42px"
  composer:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.composer}"
    padding: "14px 15px 8px"
  chat-row:
    backgroundColor: "{colors.sidebar}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "5px 8px"
    height: "42px"
  execution-summary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "18px 16px"
---

# Design System: OmniVLA

## Overview

**Creative North Star: "The Quiet Operator's Workbench"**

OmniVLA is a restrained Windows-native control surface for supervised computer use. Its atmosphere is calm, technical, and materially quiet: a dark compact conversation rail anchors the left edge, a warm paper workspace carries the operator's intent and reviewable plan, and a pale execution ledger keeps live actions and evidence visible on the right. The interface presents plans, actions, evidence, intervention, and recovery without exposing provider or model plumbing.

The core story is spatial and immediate: choose a chat, review the proposed plan, run it, watch verified actions accumulate, then complete or recover. The first viewport prioritizes the current chat, a usable plan, and execution status; it does not spend space on marketing language. Color appears as semantic state, while broad multicolor edge light belongs only to the separate execution overlay while work is active.

**Key Characteristics:**

- Dark compact conversation rail, warm central paper, and a right execution ledger.
- Dense native controls, hairline separators, and mostly flat surfaces.
- Reviewable plan and execution evidence remain visually adjacent on desktop.
- Semantic blue, green, amber, and red are state signals rather than decoration.
- Motion explains state change through opacity, short transforms, and view transitions.

## Colors

The palette is warm-neutral and near-monochrome at rest; state colors are deliberately sparse and operational.

### Primary

- **Workbench Ink:** Near-black action and text color for primary controls, assistant avatars, and active structure.
- **Focus Blue:** Reserved for keyboard focus, working state, selection, and active execution.

### Secondary

- **Verified Green:** Successful actions, ready services, and completed execution.
- **Operator Amber:** Review, operator input, elevated risk, paused, and attention states.
- **Stop Red:** Destructive actions, stopping, errors, and failure.

### Neutral

- **Conversation Charcoal:** Near-black sidebar and titlebar field.
- **Warm Canvas:** Dominant workspace background for long reading and composition.
- **White Paper:** Crisp control, composer, and footer surface.
- **Quiet Surface:** Low-contrast fill for hover, grouped content, and user messages.
- **Hairline / Strong Hairline:** Low-contrast panel, row, and field boundaries.
- **Muted / Faint Ink:** Explanation, timestamps, counts, and inactive metadata.

### Named Rules

**The State-Only Color Rule.** Saturated color communicates focus, progress, success, attention, or danger; it does not decorate idle workbench surfaces.

**The Active-Edge Rule.** Broad ambient colored edge glow appears only in the execution overlay while work is running. The primary workbench stays quiet.

## Typography

**Display Font:** Segoe UI Variable Text, falling back to Segoe UI and the system sans-serif stack.

**Body Font:** Segoe UI Variable Text, falling back to Segoe UI and the system sans-serif stack.
**Label/Mono Font:** Cascadia Mono with Consolas fallback for editable Markdown and inline technical text.

**Character:** The type system is compact, familiar, and native to Windows. Hierarchy comes from weight, small changes in size, muted color, and spacing rather than oversized headings or promotional typography.

### Hierarchy

- **Headline:** Medium-semibold fluid type with tight tracking, limited to empty or introductory workspace states.
- **Title:** Compact semibold type for chat titles, utility headers, and panel headings.
- **Body:** Regular native text for conversation and explanatory copy, normally constrained to about 72 characters per line.
- **Label:** Dense medium-weight text for state, controls, field labels, counts, and timeline metadata.
- **Mono:** A readable technical face for Markdown editing and code fragments.

### Named Rules

**The Native Density Rule.** Use the native body and label scale for operational screens; large type is exceptional and never substitutes for information hierarchy.

## Layout

Desktop uses a persistent three-column model: a 248px conversation rail, a flexible central workspace, and a 360px execution ledger. Below 1100px, the fixed rails tighten to 224px and 320px. Conversation content is centered and capped near 820px; the composer is capped near 780px so reading and action remain aligned.

At 860px and below, the execution ledger becomes a right-side overlay instead of compressing the conversation. At 700px and below, the conversation rail becomes a left drawer, the execution ledger becomes full-screen, utility layouts collapse to one column, and peripheral labels yield to icon controls. Persistent desktop chrome uses a 38px titlebar and a 54–56px session header.

The repeating rhythm is compact: 4px for micro gaps, 8–10px inside controls, 16px for panel sections, and 24px around utility content. Hairline borders define major regions; whitespace separates conversation turns and plan steps.

**The First-Viewport Rule.** The current chat, reviewable plan, and execution status must be available without passing through a welcome or marketing screen.

**The Adjacent-Evidence Rule.** On wide screens, keep plan, current evidence, and action history adjacent; on narrow screens, preserve the same hierarchy in a dedicated execution sheet.

## Elevation & Depth

The workbench is flat by default. Tonal differences and one-pixel boundaries establish structure; shadows are reserved for floating or interactive layers such as the composer focus state, context menu, mobile drawers, toast, execution overlay beacon, and captured-screen evidence. These shadows are diffuse and low-opacity rather than hard or graphic.

### Shadow Vocabulary

- **Focused Composer** (`0 7px 24px rgba(30,30,28,.08), 0 1px 4px rgba(30,30,28,.05)`): Gentle lift while writing.
- **Floating Menu** (`0 14px 36px rgba(0,0,0,.3)`): Stronger separation for dark context menus crossing surfaces.
- **Execution Evidence** (`0 7px 20px rgba(28,28,26,.1)`): Subtle lift for the latest captured screen.
- **Overlay Beacon** (`0 12px 34px rgba(25,25,23,.16), 0 2px 8px var(--state-soft)`): State-tinted floating status capsule during execution.

### Named Rules

**The Flat-at-Rest Rule.** Persistent surfaces use tone and hairlines; elevation appears only when a layer floats, receives focus, or temporarily crosses the workbench.

## Shapes

Geometry is restrained and Windows-native. Most controls and rows use gently curved 7–8px corners; grouped surfaces and message bubbles extend to 12–13px. One-pixel borders carry most structure. Circles are reserved for status dots, activity checks, spinners, and toggle handles; they are not a general container shape.

**The Compact-Corner Rule.** Default to the 8px control radius. Use larger corners only for clearly larger grouped surfaces such as the composer or a message bubble.

## Components

### Buttons

- **Shape:** Compact rounded rectangles with a minimum 38–42px desktop height and 7–8px corners.
- **Primary:** Workbench Ink fill with white text for Run, Save, Send, Record, and equivalent forward actions.
- **Hover / Focus:** Hover changes tone or adds a slight lift; keyboard focus uses a visible 2px Focus Blue outline with offset. Active feedback briefly scales to 96.5%.
- **Secondary / Ghost / Danger:** Secondary controls use White Paper with a strong hairline. Ghost controls rely on hover fill. Danger controls use Stop Red text and border, with a pale red hover fill.

### Chips

- **Style:** Suggestion and plan-choice chips are white or transparent, bounded by a strong hairline, and set in dense label text.
- **State:** Hover uses a quiet warm fill and a small upward or directional transform; chips remain secondary to the plan and Run action.

### Cards / Containers

- **Corner Style:** 8px for compact grouped content, 12–13px for messages and the composer.
- **Background:** Warm Canvas at page level, White Paper for controls, and Quiet Surface for low-emphasis grouping.
- **Shadow Strategy:** Flat at rest; shadow only when focused, floating, or carrying evidence.
- **Border:** One-pixel hairlines separate panels and rows.
- **Internal Padding:** 10px for compact notices and 16px for execution sections.

### Inputs / Fields

- **Style:** White paper, strong hairline, 7–8px corners, compact native text, and 36–42px height depending on context.
- **Focus:** Focus Blue border or a 2px visible outline; the composer also lifts by 1px with a diffuse shadow.
- **Error / Disabled:** Error treatment uses Stop Red and its pale surface. Disabled primary actions become neutral gray with no elevation.

### Navigation

The conversation rail uses charcoal rows with muted metadata, a restrained border, and a small semantic status dot. Hover raises surface contrast; the active chat uses the strongest charcoal surface and white title text. Utility navigation uses flat tabs with a two-pixel animated underline. On mobile, the rail becomes a dark off-canvas drawer with a scrim.

### Execution Ledger

The ledger is an ordered operational record, not a dashboard of model internals. A compact summary leads into review, operator request, latest screen, and activity sections. Each verified action uses a semantic check marker, short action label, result copy, and tabular step index. Progress is stated through phase and evidence, never an invented percentage.

### Execution Overlay

The always-on-top overlay uses a compact top-center beacon and a broad four-edge glow only while execution is visible. Phase changes shift the glow among blue, violet, green, amber, and red; a collapsible drawer exposes recent activity and intervention controls. Reduced-motion mode preserves state color while removing animation.

## Do's and Don'ts

### Do:

- **Do** keep the operator's request, proposed plan, and verified action history legible as one continuous workflow.
- **Do** use warm neutral surfaces and hairlines for structure before reaching for shadow or color.
- **Do** reserve semantic color for focus and execution state.
- **Do** provide a visible keyboard focus indicator and a reduced-motion equivalent.
- **Do** describe progress with phases, action counts, evidence, and completion state.

### Don't:

- **Don't** expose model, provider, token, or chain-of-thought plumbing in the primary workbench.
- **Don't** use marketing headlines, taglines, hero panels, or decorative welcome content in the first viewport.
- **Don't** show ambient edge glow while the system is idle.
- **Don't** invent completion percentages or use color as the sole carrier of execution state.
- **Don't** add hard offset shadows, oversized pills, novelty geometry, or display typography to operational surfaces.

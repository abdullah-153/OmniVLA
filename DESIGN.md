# OmniVLA — Product Design System

> A quiet local command center: one decision at a time, evidence when it matters.

This document defines how OmniVLA should feel as an application. It complements
`DESIGNv2.md`, which supplies the visual token reference; where the documents
overlap, this product-system document controls information architecture,
component density, and motion.

## Product principles

1. **One job per view.** A person should never have to plan a task, inspect a
   screen capture, tune a model, and read logs in one viewport.
2. **Evidence arrives at the moment of action.** Planning stays in Command;
   screen evidence and trace stay in Live; audit data stays in History.
3. **Chrome recedes.** Borders show ownership, not decoration. Use a surface
   only when it contains a distinct control, decision, or evidence block.
4. **Motion communicates state.** Animation must show navigation, execution,
   or a changed safety state. It must never invent progress or compete with an
   active desktop task.
5. **Local is legible.** Runtime and safety settings remain explicit, but out
   of the operator's way until requested.

## Information architecture

| Workspace | Single purpose | Includes | Explicitly excludes |
| --- | --- | --- | --- |
| **Command** | Turn an outcome into a reviewed runbook | intent composer, plan, approval | live screenshot, trace, logs, model controls |
| **Live** | Observe and direct an active run | phase, actual actions, screenshot evidence, pause/stop, HITL | planning composer, saved history, runtime settings |
| **History** | Review prior work without noise | saved runs, audit journal, runtime logs | live controls, approval flow |
| **Safety** | Decide operating boundaries | policy, approval mode, LAN pairing | task execution and model configuration |
| **Runtime** | Tune local inference deliberately | model settings, health, VRAM lane | task creation, audit stream |

The Command Center is a single-page application with discrete workspaces. Only
one workspace is rendered as active at a time. A successful approval moves the
operator to **Live**, where the current run is visible immediately.

## Layout rules

- Use a centered content column: **920px** for Command, Safety, and Runtime;
  **1100px** only for Live or History when evidence benefits from a split view.
- Maintain 20px between sibling surfaces on desktop and 16px on mobile.
- Page gutters are responsive: 16px minimum, 40px maximum.
- A surface uses 20px internal padding on desktop and 15px on mobile.
- A page heading contains one short heading and one concise supporting line.
  It is never a dashboard header with summary metrics.
- Do not stack cards inside cards. Metric cells, trace rows, and form rows may
  use hairline dividers inside their owning surface instead.
- Only Live may use a two-column layout; it pairs **screen evidence** with
  **actual trace**. At tablet width it becomes one vertical reading order.

## Visual language

The canvas is `#08090a`; owned surfaces are `#0f1011`; elevated detail is
`#161718`. Use paper-white only for headings and decisive labels. All ordinary
body text stays in the mist/fog scale.

| Role | Token | Use |
| --- | --- | --- |
| Primary action | `#e4f222` acid lime | One decisive action in a local context |
| Thinking | `#02b8cc` signal teal | Active model inference only |
| Acting | `#e4f222` acid lime | Active native input only |
| Verifying | `#6366f1` iris violet | Screen/evidence verification only |
| Intervention / error | `#eb5757` coral red | Human boundary or fault only |
| Verified completion | `#27a644` pulse green | Confirmed safe outcome only |

- Card/surface radius: 12px. Input and button radius: 6px. Badge radius: 4px.
- Borders are 0.5px graphite or quiet white; use a shadow only for a modal or
  the floating mobile navigation.
- Inter remains the interface face. Mono is reserved for state, measurements,
  timestamps, and compact labels.
- Avoid all-caps headings, bold display type, decorative gradients, and
  decorative color. The UI should feel precise, not theatrical.

## Motion system

### Navigation and desktop shell

- A workspace enters once with a 9px upward settle over **360ms** using
  `cubic-bezier(0.16, 1, 0.3, 1)`.
- Active navigation uses a one-pixel acid-lime underline that grows into place.
- The desktop Electron shell may fade in over 180ms after it is ready. The
  content UI supplies all other motion; window chrome must remain unobtrusive.

### Active execution

- The Live workspace uses a thin phase-colored line and a slow evidence-frame
  pulse. Both are tied to the actual phase received from the agent.
- The fullscreen overlay uses animated screen edges, a traveling signal rail,
  and a phase timer. It shows real action records, never a fabricated percent
  complete or a fixed step count.
- Overlay phase colors: teal = thinking, lime = acting, violet = verifying,
  coral = human input/error, lavender = paused, green = done.

### Accessibility and performance

- Animate only `transform`, `opacity`, and small color transitions. Do not add
  screen diffing, canvas sampling, polling beyond existing status updates, or
  a second perception pipeline for visual effects.
- Respect `prefers-reduced-motion`; all animation becomes effectively instant.
- An animation may never conceal a Stop, Pause, or HITL control.

## Responsive behavior

- Desktop uses the top workspace navigation. Mobile uses a fixed five-item
  navigation bar with Command, Live, History, Safety, and Runtime.
- Mobile surfaces remain 15px padded and appear in one reading column.
- Live screen evidence appears before the trace on narrow displays. Action
  controls remain visible and never depend on hover.
- Paired mobile control follows the same information architecture; it is not a
  shrunk dashboard.

## Review checklist

Before adding UI, verify:

1. Which single workspace owns this information?
2. Does it require a new surface, or can it live as a row inside an existing
   surface?
3. Does it have one clear primary action?
4. If it moves, does the animation reveal a real state transition?
5. Does it remain readable at 390px wide and with reduced motion enabled?

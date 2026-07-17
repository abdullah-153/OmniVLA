# OmniVLA: Task Decomposition
## Document 03 — Intelligent Multi-Step Planning

---

## 1. The Planning Problem

Complex user requests like *"Create a pivot table in Excel from the sales data, then email it to the team"* require **dozens of individual UI actions**. A small LLM cannot reliably plan AND execute all these actions simultaneously.

**Solution**: Separate planning from execution. The Task Decomposer converts high-level goals into ordered sequences of atomic sub-goals. Each sub-goal maps to 1-3 UI actions.

---

## 2. Decomposition Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    TASK DECOMPOSER                                │
│                                                                    │
│  Input:  "Create a pivot table from sales data and email it"     │
│                                                                    │
│  Step 1: Check memory for similar past task                      │
│  Step 2: Generate plan via LLM (GBNF-constrained JSON)          │
│  Step 3: Validate plan coherence                                 │
│  Step 4: Enrich with app-specific knowledge                     │
│                                                                    │
│  Output: [                                                        │
│    {step: 1, goal: "Click on cell A1 in the data range",         │
│     app: "Excel", category: "navigation"},                        │
│    {step: 2, goal: "Select entire data range with Ctrl+Shift+End",│
│     app: "Excel", category: "selection"},                         │
│    {step: 3, goal: "Click Insert tab in ribbon",                 │
│     app: "Excel", category: "navigation"},                        │
│    {step: 4, goal: "Click PivotTable button",                    │
│     app: "Excel", category: "action"},                            │
│    {step: 5, goal: "Click OK in PivotTable dialog",              │
│     app: "Excel", category: "confirmation"},                      │
│    ...                                                            │
│  ]                                                                │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. The Decomposition Prompt

The prompt is the most critical element. It must:
- Teach the model to think in atomic UI operations
- Prevent over-decomposition (too many tiny steps)
- Prevent under-decomposition (steps that require multiple clicks)
- Include app-awareness (different apps have different workflows)

### 3.1 System Prompt

```
You are a task planner for a Windows desktop automation agent.

Your job is to decompose user requests into ATOMIC sub-goals.
Each sub-goal should correspond to ONE observable UI action:
- One click on a specific UI element
- One keyboard shortcut
- One text entry into a field
- One scroll action

RULES:
1. Each step = ONE UI action. "Click the File menu" is one step.
   "Open a new document" might be 2-3 steps (File → New → Blank).
2. Be SPECIFIC. Say "Click the 'Compose' button" not "Open compose".
3. Include which application each step targets.
4. Use keyboard shortcuts when they're faster and more reliable.
   Example: "Save file" → "Press Ctrl+S" instead of "Click File → Save".
5. For text entry, specify the EXACT text to type.
6. Maximum 15 steps. If the task needs more, break it into phases.
7. Consider the STARTING STATE. If the app isn't open, include 
   steps to open it.
8. Group related micro-actions. "Click cell A1" is one step, not
   "Move mouse to A1" + "Click left button".

OUTPUT FORMAT: JSON with a "plan" array.
```

### 3.2 User Prompt Template

```
Break this task into atomic steps:

TASK: {user_task}

CURRENT APP: {active_app}  (or "Desktop" if no app is focused)

Output the plan as JSON:
```

### 3.3 GBNF Grammar for Plan Output

```ebnf
root ::= "{" ws "\"plan\":" ws "[" ws plan-items ws "]" ws "}"

plan-items ::= plan-item ("," ws plan-item)*

plan-item ::= "{" ws
    "\"step\":" ws step-number "," ws
    "\"goal\":" ws "\"" goal-text "\"" "," ws
    "\"app_hint\":" ws "\"" app-name "\""
    ws "}"

step-number ::= [1-9] [0-9]?
goal-text ::= [^"]{5,200}
app-name ::= [A-Za-z ]{2,30}
ws ::= " "?
```

This grammar ensures the LLM **can only** produce valid JSON plans. No hallucinated formats possible.

---

## 4. App-Aware Decomposition

Different applications have different interaction paradigms. The decomposer should be aware of these patterns:

### 4.1 Shortcut Knowledge Base

```python
APP_PATTERNS = {
    "Excel": {
        "save": "Press Ctrl+S",
        "new_workbook": "Press Ctrl+N",
        "undo": "Press Ctrl+Z",
        "redo": "Press Ctrl+Y",
        "copy": "Press Ctrl+C",
        "paste": "Press Ctrl+V",
        "select_all": "Press Ctrl+A",
        "find": "Press Ctrl+F",
        "find_replace": "Press Ctrl+H",
        "bold": "Press Ctrl+B",
        "italic": "Press Ctrl+I",
        "insert_row": "Right-click row header → Click Insert",
        "insert_column": "Right-click column header → Click Insert",
        "format_cells": "Press Ctrl+1",
        "new_sheet": "Click + button next to sheet tabs",
        "rename_sheet": "Double-click sheet tab",
    },
    "Chrome": {
        "new_tab": "Press Ctrl+T",
        "close_tab": "Press Ctrl+W",
        "address_bar": "Press Ctrl+L",
        "search": "Press Ctrl+L, then type search query",
        "refresh": "Press F5",
        "back": "Press Alt+Left",
        "forward": "Press Alt+Right",
        "developer_tools": "Press F12",
        "downloads": "Press Ctrl+J",
        "history": "Press Ctrl+H",
        "bookmarks": "Press Ctrl+D",
        "print": "Press Ctrl+P",
    },
    "VS Code": {
        "command_palette": "Press Ctrl+Shift+P",
        "save": "Press Ctrl+S",
        "open_file": "Press Ctrl+O",
        "open_terminal": "Press Ctrl+`",
        "find": "Press Ctrl+F",
        "find_replace": "Press Ctrl+H",
        "go_to_line": "Press Ctrl+G",
        "toggle_sidebar": "Press Ctrl+B",
        "new_file": "Press Ctrl+N",
    },
    "File Explorer": {
        "new_folder": "Press Ctrl+Shift+N",
        "rename": "Press F2",
        "delete": "Press Delete",
        "copy": "Press Ctrl+C",
        "paste": "Press Ctrl+V",
        "address_bar": "Press Ctrl+L",
        "search": "Press Ctrl+E",
        "properties": "Press Alt+Enter",
        "select_all": "Press Ctrl+A",
    },
}
```

### 4.2 Enrichment Pass

After the LLM generates the raw plan, an enrichment pass replaces verbose click sequences with shortcuts:

```python
def enrich_plan(plan: list[SubGoal], active_app: str) -> list[SubGoal]:
    """Replace click-based steps with shortcuts where possible."""
    shortcuts = APP_PATTERNS.get(active_app, {})
    
    enriched = []
    for goal in plan:
        goal_lower = goal.goal.lower()
        
        # Check if this step can be replaced with a shortcut
        replaced = False
        for intent, shortcut in shortcuts.items():
            if intent.replace("_", " ") in goal_lower:
                goal.goal = shortcut
                replaced = True
                break
        
        enriched.append(goal)
    
    return enriched
```

---

## 5. Hierarchical Decomposition

For very complex tasks, a single decomposition pass might produce too many steps. We use **hierarchical decomposition**:

### 5.1 Two-Level Planning

```
Level 1: PHASES (high-level milestones)
  Phase 1: "Prepare the data in Excel"
  Phase 2: "Create the pivot table"
  Phase 3: "Email the result"

Level 2: STEPS (atomic UI actions within each phase)
  Phase 1:
    Step 1.1: "Open Excel"
    Step 1.2: "Open the sales data file"
    Step 1.3: "Select data range A1:F100"
    ...
```

### 5.2 When to Use Hierarchical Decomposition

```python
def decompose(self, task: str) -> list[SubGoal]:
    """Decide between flat and hierarchical decomposition."""
    
    # Estimate task complexity
    complexity_indicators = [
        "and then",      # Multi-phase
        "after that",    # Sequential phases
        "multiple",      # Multiple targets
        "each",          # Iteration required
        "all",           # Batch operation
        "spreadsheet",   # Complex app
        "pivot",         # Complex operation
        "email",         # Cross-app operation
    ]
    
    complexity = sum(1 for ind in complexity_indicators 
                     if ind in task.lower())
    
    if complexity >= 3:
        # Complex task → hierarchical decomposition
        phases = self._decompose_phases(task)
        all_steps = []
        for phase in phases:
            steps = self._decompose_steps(phase)
            all_steps.extend(steps)
        return all_steps
    else:
        # Simple task → flat decomposition
        return self._decompose_steps(task)
```

---

## 6. Dynamic Re-Planning

The initial plan is a *prediction*. The actual UI may differ from what the LLM expected. When verification detects an unexpected state, the decomposer is called again to re-plan from the current state.

### 6.1 Re-Planning Trigger

```python
def handle_unexpected_state(self, current_state, expected_outcome, 
                            remaining_goals):
    """Re-plan when the current state doesn't match expectations."""
    
    re_plan_prompt = f"""
    The agent was executing a plan but encountered an unexpected state.
    
    ORIGINAL REMAINING GOALS:
    {format_goals(remaining_goals)}
    
    CURRENT SCREEN STATE:
    {current_state.to_prompt_string()}
    
    UNEXPECTED SITUATION:
    The last action did not produce the expected result.
    
    Generate a NEW plan from the current state to achieve
    the remaining goals. You may need to adapt the approach.
    """
    
    return self.decompose(re_plan_prompt)
```

### 6.2 Re-Planning Budget

To prevent infinite re-planning loops:
- Maximum 3 re-plans per task
- Maximum 25 total steps across all plans
- If all re-plans fail, escalate to user

---

## 7. Example Decompositions

### 7.1 Simple Task

**User**: "Save this document"

```json
{
  "plan": [
    {"step": 1, "goal": "Press Ctrl+S", "app_hint": "Current App"}
  ]
}
```

### 7.2 Medium Task

**User**: "Open Chrome and search for weather in New York"

```json
{
  "plan": [
    {"step": 1, "goal": "Press Windows key", "app_hint": "Desktop"},
    {"step": 2, "goal": "Type 'Chrome'", "app_hint": "Start Menu"},
    {"step": 3, "goal": "Press Enter to open Chrome", "app_hint": "Start Menu"},
    {"step": 4, "goal": "Press Ctrl+L to focus address bar", "app_hint": "Chrome"},
    {"step": 5, "goal": "Type 'weather in New York'", "app_hint": "Chrome"},
    {"step": 6, "goal": "Press Enter to search", "app_hint": "Chrome"}
  ]
}
```

### 7.3 Complex Task

**User**: "Create a new Excel spreadsheet with columns for Name, Email, and Department, then save it as employees.xlsx on the Desktop"

```json
{
  "plan": [
    {"step": 1, "goal": "Press Windows key", "app_hint": "Desktop"},
    {"step": 2, "goal": "Type 'Excel'", "app_hint": "Start Menu"},
    {"step": 3, "goal": "Press Enter to open Excel", "app_hint": "Start Menu"},
    {"step": 4, "goal": "Click 'Blank workbook'", "app_hint": "Excel"},
    {"step": 5, "goal": "Type 'Name' in cell A1", "app_hint": "Excel"},
    {"step": 6, "goal": "Press Tab to move to B1", "app_hint": "Excel"},
    {"step": 7, "goal": "Type 'Email'", "app_hint": "Excel"},
    {"step": 8, "goal": "Press Tab to move to C1", "app_hint": "Excel"},
    {"step": 9, "goal": "Type 'Department'", "app_hint": "Excel"},
    {"step": 10, "goal": "Press Ctrl+S to save", "app_hint": "Excel"},
    {"step": 11, "goal": "Navigate to Desktop in save dialog", "app_hint": "Excel"},
    {"step": 12, "goal": "Type 'employees' in filename field", "app_hint": "Excel"},
    {"step": 13, "goal": "Click Save button", "app_hint": "Excel"}
  ]
}
```

---

## 8. Validation & Error Prevention

### 8.1 Plan Coherence Checks

After decomposition, validate the plan before execution:

```python
def validate_plan(plan: list[SubGoal]) -> list[str]:
    """Check plan for common issues. Returns list of warnings."""
    warnings = []
    
    # Check for empty steps
    for g in plan:
        if not g.goal.strip():
            warnings.append(f"Step {g.step} has empty goal")
    
    # Check for duplicate consecutive steps
    for i in range(1, len(plan)):
        if plan[i].goal == plan[i-1].goal:
            warnings.append(f"Steps {i} and {i+1} are identical")
    
    # Check step count
    if len(plan) > 15:
        warnings.append("Plan has >15 steps — consider breaking into phases")
    
    # Check for app transitions without wait
    for i in range(1, len(plan)):
        if plan[i].app_hint != plan[i-1].app_hint:
            # App switch detected — should we add a wait?
            if not any(w in plan[i].goal.lower() 
                      for w in ["wait", "press", "key"]):
                warnings.append(
                    f"Step {i+1} switches to {plan[i].app_hint} "
                    f"— may need wait for app to load"
                )
    
    return warnings
```

---

## 9. Memory-Enhanced Planning

Before generating a new plan, the decomposer queries episodic memory for similar past tasks:

```python
def decompose_with_memory(self, task: str) -> list[SubGoal]:
    """Generate plan using past successful trajectories as examples."""
    
    # Query memory for similar past tasks
    past_trajectory = self.memory.recall(task, n_results=1)
    
    if past_trajectory:
        # Include past trajectory as a few-shot example
        memory_context = f"""
        SIMILAR PAST TASK (successful):
        Task: {past_trajectory.task}
        Steps taken: {format_trajectory(past_trajectory)}
        
        Use this as reference but adapt to the current task.
        """
    else:
        memory_context = ""
    
    # Generate plan with memory context
    return self._llm_decompose(task, memory_context)
```

This allows the agent to **learn from experience**: if a similar task was completed successfully before, the decomposer uses that trajectory as a template.

---

*Document Version: 1.0 | Part 03 of 08*
*See also: [04_Action_Reasoning](./04_Action_Reasoning.md) for per-step decision making*

# OmniVLA: Memory & Verification
## Document 06 — Episodic Memory and Action Verification

---

## 1. Why Memory Matters

Without memory, the agent starts from zero every session. It re-learns that "Compose" is element 1 in Gmail every single time. Memory transforms the agent from a **stateless tool** into a **learning system**.

### Memory Benefits

| Without Memory | With Memory |
|---------------|------------|
| Every task starts cold | Past successes inform current actions |
| Same mistakes repeated | Known failures are avoided |
| No adaptation to user workflow | Agent learns user's app preferences |
| Full LLM reasoning every step | Memory-matched steps skip reasoning |
| ~800ms per action | ~100ms for memory-matched actions |

---

## 2. Episodic Memory Architecture

### 2.1 What is an Episode?

An **episode** is a single (state → action → result) tuple:

```python
@dataclass
class Episode:
    # Context
    task: str               # "Send email to john@example.com"
    app_context: str        # "Gmail"
    goal: str               # "Click Compose button"
    
    # Action taken
    action_type: str        # "click"
    action_args: list[str]  # ["1"]
    action_method: str      # "shortcut" | "uia" | "coordinate"
    
    # Result
    success: bool           # True
    state_summary: str      # "Gmail inbox, Compose button visible"
    outcome: str            # "Compose window opened"
    
    # Metadata
    timestamp: float
    execution_time_ms: int
    retry_count: int
```

### 2.2 Storage Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    EPISODIC MEMORY SYSTEM                         │
│                                                                    │
│  ┌────────────────────┐    ┌────────────────────────────────┐   │
│  │   ChromaDB          │    │   Embedding Model              │   │
│  │   (Persistent)      │    │   all-MiniLM-L6-v2             │   │
│  │                     │    │   22MB, CPU-only                │   │
│  │   Collection:       │    │                                │   │
│  │   "episodes"        │◄───│   Text → 384-dim vector        │   │
│  │                     │    │                                │   │
│  │   ~50ms query time  │    │   ~5ms per embedding           │   │
│  └────────────────────┘    └────────────────────────────────┘   │
│                                                                    │
│  Storage: ~1KB per episode                                       │
│  Capacity: 100,000+ episodes in <100MB                           │
│  Location: ./omnivla_memory/ (local directory)                   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Document Format

Each episode is stored as a searchable text document with structured metadata:

```python
def store(self, episode: Episode):
    """Store a successful episode."""
    # The document text is what gets embedded for similarity search
    document = (
        f"App: {episode.app_context} | "
        f"Goal: {episode.goal} | "
        f"Action: {episode.action_type}({', '.join(episode.action_args)}) | "
        f"State: {episode.state_summary}"
    )
    
    # Metadata for filtering and retrieval
    metadata = {
        "task": episode.task,
        "app": episode.app_context,
        "goal": episode.goal,
        "action_type": episode.action_type,
        "action_args": json.dumps(episode.action_args),
        "action_method": episode.action_method,
        "success": episode.success,
        "timestamp": episode.timestamp,
    }
    
    # Unique ID based on timestamp
    doc_id = f"ep_{int(episode.timestamp * 1000)}"
    
    self._collection.add(
        documents=[document],
        metadatas=[metadata],
        ids=[doc_id]
    )
```

---

## 3. Memory Retrieval

### 3.1 Recall Pipeline

```
Current State:
  App: Gmail
  Goal: "Click the Compose button"
                │
                ▼
        ┌───────────────┐
        │ Build Query   │  "App: Gmail | Goal: Click Compose"
        └───────┬───────┘
                │
                ▼
        ┌───────────────┐
        │ Embed Query   │  [0.12, -0.34, 0.87, ...]  (384-dim)
        └───────┬───────┘
                │
                ▼
        ┌───────────────┐
        │ ChromaDB      │  Find top-3 similar episodes
        │ Similarity    │  Filter: success=True, app=Gmail
        │ Search        │
        └───────┬───────┘
                │
                ▼
        ┌───────────────┐
        │ Format for    │  "Previously: click(1) succeeded 
        │ LLM Prompt    │   for 'Click Compose' in Gmail"
        └───────────────┘
```

### 3.2 Recall Implementation

```python
def recall(self, goal: str, app_context: str = "", 
           n_results: int = 3) -> str:
    """Retrieve relevant past experiences."""
    if not self._available or self._collection.count() == 0:
        return ""
    
    query = f"App: {app_context} | Goal: {goal}"
    
    results = self._collection.query(
        query_texts=[query],
        n_results=min(n_results, self._collection.count()),
        where={"success": True}  # Only retrieve successful episodes
    )
    
    if not results["documents"][0]:
        return ""
    
    # Format as prompt context
    memories = []
    for doc, meta in zip(results["documents"][0], 
                          results["metadatas"][0]):
        action_args = json.loads(meta.get("action_args", "[]"))
        memories.append(
            f"Previously: for goal '{meta['goal']}' in {meta['app']}, "
            f"action {meta['action_type']}({', '.join(action_args)}) "
            f"succeeded."
        )
    
    return " | ".join(memories[:3])
```

### 3.3 Memory-Accelerated Execution

When memory returns a high-confidence match, we can **skip LLM inference entirely**:

```python
def reason_with_memory(self, goal, state, memory_context):
    """Try memory shortcut before LLM reasoning."""
    
    # Check for exact memory match
    exact_match = self.memory.exact_recall(goal, state.app)
    
    if exact_match and exact_match.confidence > 0.95:
        # High-confidence memory hit — skip LLM
        logger.info("Memory hit! Replaying: %s(%s)", 
                    exact_match.action_type, exact_match.action_args)
        return AgentAction(
            action_type=exact_match.action_type,
            args=exact_match.action_args,
            thought="Replaying from memory",
            raw="MEMORY_REPLAY"
        )
    
    # No confident match — use LLM with memory as context
    return self.reasoner.reason(goal, state, memory_context)
```

This can reduce per-step latency from ~800ms to ~100ms for known actions.

---

## 4. Trajectory Learning

### 4.1 Full Trajectory Storage

Beyond individual episodes, we store entire task trajectories:

```python
@dataclass
class Trajectory:
    task: str                    # Original user request
    episodes: list[Episode]      # Ordered sequence of episodes
    total_time_ms: int           # Total execution time
    success: bool                # Did the overall task succeed?
    app_sequence: list[str]      # Apps used in order
```

### 4.2 Trajectory Matching

For complex multi-step tasks, trajectory matching provides a template:

```python
def recall_trajectory(self, task: str) -> Trajectory | None:
    """Find a past trajectory similar to the current task."""
    
    query = f"Task: {task}"
    results = self._trajectory_collection.query(
        query_texts=[query],
        n_results=1,
        where={"success": True}
    )
    
    if results["documents"][0]:
        return deserialize_trajectory(results["documents"][0])
    return None
```

This enables **one-shot task learning**: after successfully completing a task once, the agent can replay the trajectory with minimal reasoning.

---

## 5. Action Verification

### 5.1 Why Verification Matters

Without verification, the agent is "fire and forget" — it executes actions blindly and hopes they worked. This leads to silent failures that compound through multi-step tasks.

### 5.2 Three-Layer Verification

```
Layer 1: SCREEN DIFF (Fast, Coarse)
┌────────────────────────────────────────────────────────┐
│ Compare before/after screenshots using pixel diff      │
│ If <1% pixels changed → action probably had no effect  │
│ If >30% pixels changed → major state transition        │
│ Time: ~5ms                                             │
└────────────────────────────────────────────────────────┘
           │
           ▼
Layer 2: SEMANTIC VERIFICATION (Medium, Precise)
┌────────────────────────────────────────────────────────┐
│ Re-run perception after action                         │
│ Compare old state vs new state semantically            │
│ Check: did the expected outcome occur?                 │
│ Time: ~150ms                                           │
└────────────────────────────────────────────────────────┘
           │
           ▼
Layer 3: GOAL VERIFICATION (Slow, Deep)
┌────────────────────────────────────────────────────────┐
│ Ask the LLM: "Given the new state, is the sub-goal    │
│ now complete?"                                         │
│ Used only when semantic verification is ambiguous      │
│ Time: ~500ms                                           │
└────────────────────────────────────────────────────────┘
```

### 5.3 Screen Diff Implementation

```python
import numpy as np

def compute_screen_diff(before_frame, after_frame, 
                        threshold: int = 30) -> dict:
    """Compare two screenshots and return diff metrics."""
    if before_frame.shape != after_frame.shape:
        return {"changed": True, "diff_ratio": 1.0, 
                "description": "Resolution changed"}
    
    # Pixel-wise difference
    diff = np.abs(before_frame.astype(int) - after_frame.astype(int))
    changed_pixels = np.any(diff > threshold, axis=2)
    diff_ratio = float(changed_pixels.sum()) / changed_pixels.size
    
    # Classify the change
    if diff_ratio < 0.01:
        description = "No visible change"
        changed = False
    elif diff_ratio < 0.05:
        description = "Minor change (tooltip, cursor, highlight)"
        changed = True
    elif diff_ratio < 0.15:
        description = "Moderate change (menu opened, element selected)"
        changed = True
    elif diff_ratio < 0.50:
        description = "Significant change (dialog opened, page scrolled)"
        changed = True
    else:
        description = "Major change (new window, page navigation)"
        changed = True
    
    return {
        "changed": changed,
        "diff_ratio": diff_ratio,
        "description": description
    }
```

### 5.4 Semantic Verification

```python
def verify_semantically(old_state, new_state, action, 
                        expected_outcome: str) -> bool:
    """Check if the action produced the expected semantic change."""
    
    # Check for new elements that suggest success
    old_labels = {e.label for e in old_state.elements}
    new_labels = {e.label for e in new_state.elements}
    
    new_elements = new_labels - old_labels
    removed_elements = old_labels - new_labels
    
    # Action-specific verification
    if action.action_type == "click":
        # After clicking a menu item, new items should appear
        if "menu" in action.thought.lower():
            return len(new_elements) > 0
        
        # After clicking a tab, the tab should be active
        if "tab" in action.thought.lower():
            return new_state.layout_type != old_state.layout_type or \
                   len(new_elements) > 0
    
    elif action.action_type == "type":
        # After typing, the text should appear somewhere
        typed_text = action.args[0]
        return any(typed_text.lower() in e.label.lower() 
                  for e in new_state.elements)
    
    # Fallback: any visible change counts as potential success
    return len(new_elements) > 0 or len(removed_elements) > 0
```

---

## 6. Failure Detection & Recovery

### 6.1 Failure Indicators

```python
def detect_failure(diff_result, old_state, new_state, 
                   action) -> str | None:
    """Detect if an action failed. Returns failure reason or None."""
    
    # No screen change after action
    if not diff_result["changed"] and action.action_type != "wait":
        return "No visible screen change after action"
    
    # Unexpected dialog appeared
    if new_state.is_dialog and not old_state.is_dialog:
        dialog_text = new_state.visible_text_summary.lower()
        if any(w in dialog_text for w in ["error", "warning", "failed"]):
            return f"Error dialog appeared: {new_state.visible_text_summary}"
    
    # Application crashed
    if new_state.app != old_state.app and \
       old_state.app not in new_state.window_title:
        return f"Application may have crashed: was {old_state.app}, now {new_state.app}"
    
    return None  # No failure detected
```

### 6.2 Recovery Strategies

```python
class RecoveryManager:
    """Manages error recovery with escalating strategies."""
    
    def recover(self, failure_reason: str, action: AgentAction,
                state: SemanticState, attempt: int) -> str:
        """Determine recovery strategy."""
        
        if attempt == 1:
            # Strategy 1: Simple retry
            return "retry_same"
        
        elif attempt == 2:
            # Strategy 2: Try alternative execution method
            if action.action_type == "click":
                return "try_alternative_method"
            else:
                return "retry_same"
        
        elif attempt == 3:
            # Strategy 3: Re-perceive and re-reason
            return "re_perceive_and_reason"
        
        elif attempt == 4:
            # Strategy 4: Re-plan from current state
            return "re_plan"
        
        else:
            # Strategy 5: Give up and ask user
            return "escalate_to_user"
```

---

## 7. Memory Maintenance

### 7.1 Garbage Collection

Over time, the memory database grows. We need to prune stale entries:

```python
def cleanup_memory(self, max_age_days: int = 30, 
                   max_episodes: int = 10000):
    """Remove old or low-value episodes."""
    cutoff = time.time() - (max_age_days * 86400)
    
    # Remove old failed episodes (failures are less useful over time)
    self._collection.delete(
        where={
            "$and": [
                {"success": False},
                {"timestamp": {"$lt": cutoff}}
            ]
        }
    )
    
    # If still too many, remove oldest entries
    if self._collection.count() > max_episodes:
        # Keep the most recent max_episodes
        all_ids = self._collection.get(
            include=["metadatas"]
        )
        sorted_by_time = sorted(
            zip(all_ids["ids"], all_ids["metadatas"]),
            key=lambda x: x[1].get("timestamp", 0)
        )
        to_remove = [id for id, _ in sorted_by_time[:-max_episodes]]
        if to_remove:
            self._collection.delete(ids=to_remove)
```

### 7.2 Memory Consolidation

Group similar episodes into consolidated memories:

```python
def consolidate(self):
    """Merge similar episodes into consolidated action patterns."""
    # Group by (app, goal_type)
    groups = defaultdict(list)
    
    all_episodes = self._collection.get(
        include=["metadatas", "documents"]
    )
    
    for meta in all_episodes["metadatas"]:
        key = (meta["app"], meta["action_type"])
        groups[key].append(meta)
    
    # For each group, identify the most reliable action
    for (app, action_type), episodes in groups.items():
        successful = [e for e in episodes if e["success"]]
        if len(successful) >= 3:
            # This action pattern is reliable — boost its weight
            # (Implementation: store as a "consolidated" episode)
            pass
```

---

## 8. Memory-Driven Optimization

### 8.1 Shortcut Discovery

The memory system can discover patterns that suggest adding new shortcuts:

```python
def discover_shortcuts(self) -> list[dict]:
    """Identify frequent actions that could be shortcut-accelerated."""
    all_episodes = self._collection.get(include=["metadatas"])
    
    # Count action frequencies by (app, goal)
    freq = Counter()
    for meta in all_episodes["metadatas"]:
        if meta["success"] and meta["action_method"] == "coordinate":
            freq[(meta["app"], meta["goal"])] += 1
    
    # Suggest shortcuts for frequent coordinate-click actions
    suggestions = []
    for (app, goal), count in freq.most_common(10):
        if count >= 5:
            suggestions.append({
                "app": app,
                "goal": goal,
                "frequency": count,
                "suggestion": f"Consider adding a keyboard shortcut "
                             f"for '{goal}' in {app}"
            })
    
    return suggestions
```

---

*Document Version: 1.0 | Part 06 of 08*
*See also: [07_Model_Selection_And_Optimization](./07_Model_Selection_And_Optimization.md) for LLM deployment*

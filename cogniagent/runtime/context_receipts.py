"""Describe personal context actually included in accepted planner requests."""
import json
import re


def personal_context_receipts(personal_context, messages):
    match = re.search(r"<personal_context>([\s\S]*?)</personal_context>", str(personal_context))
    if not match or not any(item.get("role") == "system" and match.group(0) in item.get("content", "")
                            for item in messages):
        return []
    try:
        data = json.loads(match.group(1))
        if not isinstance(data, dict):
            return []
        receipts = []

        def add(kind, label, source="Personal memory"):
            if label and len(receipts) < 10:
                item = {"kind": kind, "label": str(label)[:160], "source": source}
                if item not in receipts:
                    receipts.append(item)

        references = data.get("references", [])
        if data.get("name"):
            add("fact", "Name: " + str(data["name"]))
        for category, preferences in data.get("preferences", {}).items():
            for key, value in preferences.items():
                reference = next((ref for ref in references if ref.get("key") == f"preference:{category}:{key}"
                                  or ref.get("key", "").startswith("scoped:") and
                                  ref["key"].rsplit(":", 2)[-2:] == [category, key]), {})
                scope = reference.get("scope", "global")
                source = "Settings" if reference.get("source") == "settings" else "Personal memory"
                add("preference", f"{category} {key}: {value}" + (f" ({scope})" if scope != "global" else ""), source)
        for fact in data.get("relevant_facts", []):
            add("fact", fact)
        for entity in data.get("linked_context", []):
            add("entity", entity.get("entity"))
            for link in entity.get("links", []):
                subject, target = entity.get("entity", ""), link.get("entity", "")
                if link.get("direction") == "incoming":
                    subject, target = target, subject
                add("relation", f"{subject} → {link.get('relation', '')} → {target}")
        for workflow in data.get("successful_workflows", []):
            add("workflow", workflow.get("intent"), "Completed task")
        for conflict in data.get("conflicts", []):
            options = "; ".join(f"{option.get('scope', '')} = {option.get('value', '')}"
                                for option in conflict.get("options", []))
            add("conflict", f"{conflict.get('category', '')} {conflict.get('key', '')}: {options}", "Needs clarification")
        return receipts
    except (ValueError, TypeError, AttributeError, KeyError):
        # Malformed or external injected context cannot substantiate a receipt.
        return []

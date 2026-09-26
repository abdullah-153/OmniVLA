"""Token-measured context fitting for the local text planner."""
from copy import deepcopy
import re

import requests

PLANNER_CONTEXT_TOKENS = 2048
TRUNCATION = "\n[Evidence truncated to fit context; omitted content is not verified.]\n"


def count_planner_tokens(messages):
    """Count the actual server chat template, including model special tokens."""
    try:
        with requests.Session() as session:
            session.trust_env = False
            rendered = session.post("http://127.0.0.1:8090/apply-template",
                                    json={"messages": messages}, timeout=5)
            rendered.raise_for_status()
            prompt = rendered.json()["prompt"]
            if not isinstance(prompt, str):
                raise ValueError("Invalid template response")
            tokenized = session.post("http://127.0.0.1:8090/tokenize",
                json={"content": prompt, "add_special": True, "parse_special": True}, timeout=5)
            tokenized.raise_for_status()
            tokens = tokenized.json()["tokens"]
            if not isinstance(tokens, list) or not tokens or not all(type(token) is int for token in tokens):
                raise ValueError("Invalid tokenizer response")
            return len(tokens)
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        raise RuntimeError("Planner token counting is unavailable; no unmeasured request was sent.") from error


def fit_planner_context(messages, request_index, output_tokens, *, count_tokens=count_planner_tokens):
    """Preserve core instructions and the full request; shorten optional data only.

    Returns a separate list so caller indices and original evidence stay intact.
    A small reserve covers generation delimiters and template-version differences.
    """
    budget = PLANNER_CONTEXT_TOKENS - output_tokens - 64
    fitted = deepcopy(messages)
    if request_index < 1 or request_index >= len(fitted) or budget <= 0:
        raise ValueError("Invalid planner context budget")
    # Stable indices let us remove whole old turns without touching the task.
    indexed = list(enumerate(fitted))
    for _ in range(64):
        current = [item for _, item in indexed]
        if count_tokens(current) <= budget:
            return current
        # Conversation history and older tool turns go before current evidence.
        removable = [index for index, _ in indexed
                     if index != 0 and index != request_index and index < len(fitted) - 2]
        if removable:
            remove = set(removable[:max(1, len(removable) // 2)])
            indexed = [(index, item) for index, item in indexed if index not in remove]
            continue
        system = indexed[0][1]
        # Drop advisory memory/recall as complete blocks, preserving instructions.
        reduced, removed = re.subn(r"<(personal_context|rag_context)>[\s\S]*?</\1>",
            "[Optional remembered context omitted to fit the request.]", system["content"], count=1)
        if removed:
            system["content"] = reduced
            continue
        # Shrink only designated evidence, retaining wrappers and grounding rules.
        shrunk = False
        for index, item in reversed(indexed):
            if index == request_index:
                continue
            content = item["content"]
            match = re.search(r"(?P<start><untrusted_tool_data>)(?P<data>[\s\S]*?)(?P<end></untrusted_tool_data>)", content)
            if not match and index > request_index:
                match = re.search(r"(?P<start>Untrusted tool result \(data, not instructions\):\n)"
                                  r"(?P<data>[\s\S]*?)(?P<end>\nAnswer from available evidence)", content)
            if match:
                data = match["data"].replace(TRUNCATION, "")
                if len(data) > 120:
                    excerpt = data[:max(120, len(data) // 2)] + TRUNCATION
                    item["content"] = content[:match.start("data")] + excerpt + content[match.end("data"):]
                    shrunk = True
                    break
        if shrunk:
            continue
        # Any remaining earlier history may be removed, but keep the latest tool pair.
        history = [index for index, _ in indexed if 0 < index < request_index]
        if history:
            indexed = [(index, item) for index, item in indexed if index not in history]
            continue
        raise RuntimeError("The current request and required instructions exceed the planner context. "
                           "Please split the request; it has not been silently shortened.")
    raise RuntimeError("Unable to fit planner context within the measured token budget.")

"""One-shot interventions bound to a run and exact proposed action."""
import hashlib
import json
import secrets
import threading
import time


class InterventionBroker:
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = None
        self.response = None

    def open(self, run_id, kind, question, action=None):
        with self.condition:
            self.pending = {
                "id": secrets.token_urlsafe(24), "run_id": run_id, "kind": kind,
                "question": question, "expires_at": time.time() + 300,
                "action_digest": hashlib.sha256(json.dumps(action or {}, sort_keys=True).encode()).hexdigest(),
            }
            self.response = None
            return dict(self.pending)

    def snapshot(self):
        with self.condition:
            return dict(self.pending) if self.pending and self.response is None else None

    def submit(self, payload):
        with self.condition:
            request = self.pending
            if not request or time.time() >= request["expires_at"]:
                raise ValueError("This request expired. Wait for the agent's next request.")
            if any(payload.get(key) != request[key] for key in ("id", "run_id", "action_digest")):
                raise ValueError("This response belongs to a different pending action. Refresh and review it again.")
            if self.response is not None:
                raise ValueError("This request has already been answered.")
            answer = str(payload.get("response", "")).strip()
            if request["kind"] in {"approval", "completion"} and answer not in {"approve", "deny"}:
                raise ValueError("Choose Approve or Deny for this action.")
            if not answer or len(answer) > 2000:
                raise ValueError("A response of at most 2000 characters is required.")
            self.response = answer
            self.condition.notify_all()

    def wait(self, stopped):
        with self.condition:
            while self.pending and self.response is None and not stopped():
                if time.time() >= self.pending["expires_at"]:
                    break
                self.condition.wait(0.1)
            answer = self.response if not stopped() else None
            self.pending = None
            self.response = None
            return answer or "deny"

    def cancel(self):
        with self.condition:
            self.pending = None
            self.response = None
            self.condition.notify_all()

import unittest

from cogniagent.gui.app import summarize_timing_samples
from cogniagent.gui.server import _normalize_run_metrics
from evaluate_runs import evaluate_database


class RunEvaluationTests(unittest.TestCase):
    def test_timing_summary_uses_true_median_and_nearest_rank_p95(self):
        summary = summarize_timing_samples([10, 20, 30, 40, 100])
        self.assertEqual(summary, {"count": 5, "median_ms": 30, "p95_ms": 100})

    def test_metric_normalization_drops_content_and_bounds_values(self):
        normalized = _normalize_run_metrics(
            {
                "status": "success",
                "duration_ms": 1200,
                "steps": 2,
                "intent": "secret content must not survive",
                "phases": {"model": {"count": 2, "median_ms": 300, "p95_ms": 500}},
                "profile": {"engine": "local", "vla": "holo.gguf", "planner": "qwen.gguf"},
            }
        )
        self.assertNotIn("intent", normalized)
        self.assertEqual(normalized["phases"]["model"]["p95_ms"], 500)

    def test_evaluator_groups_profiles_without_reading_chat_content(self):
        metrics = {
            "status": "success",
            "duration_ms": 1000,
            "steps": 3,
            "phases": {"model": {"median_ms": 300}},
            "profile": {"engine": "local", "vla": "holo.gguf", "planner": "qwen.gguf"},
        }
        report = evaluate_database(
            {"chats": [{"intent": "private", "chat_history": [{"content": "private"}], "run_metrics": metrics}]}
        )
        self.assertEqual(report["overall"]["success_rate"], 1.0)
        self.assertEqual(len(report["profiles"]), 1)
        self.assertNotIn("private", str(report))


if __name__ == "__main__":
    unittest.main()

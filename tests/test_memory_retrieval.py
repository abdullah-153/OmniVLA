"""Regression tests for private, low-latency conversation recall."""

from pathlib import Path

from cogniagent.memory.chats_rag import ChatsRAG


def test_fts_recall_is_ranked_diverse_redacted_and_excludes_current_chat(tmp_path: Path):
    recall = ChatsRAG(str(tmp_path))
    try:
        recall.index_message("alpha", "user", "Use the cobalt export workflow for invoices")
        recall.index_message("alpha", "user", "Use the cobalt export workflow for invoices")
        recall.index_message("beta", "assistant", "Cobalt invoices are exported as PDF")
        recall.index_message("current", "user", "cobalt must never be recalled from this chat")
        recall.index_message("secret", "user", "cobalt api_key=abcdefghijklmnop")

        context = recall.search_context("cobalt invoice export", "current", n_results=4)
        assert "current chat" not in context
        assert context.count("Use the cobalt export workflow") == 1
        assert "[redacted secret]" in context
        assert len(context) <= 1200
    finally:
        recall.close()


def test_legacy_json_is_migrated_once(tmp_path: Path):
    legacy = tmp_path / "chat_rag_store.json"
    legacy.write_text(
        '[{"chat_id":"old","role":"user","content":"remember nebula layout","timestamp":1}]',
        encoding="utf-8",
    )
    recall = ChatsRAG(str(tmp_path))
    try:
        assert "nebula layout" in recall.search_context("nebula", "new")
        assert not legacy.exists()
        assert (tmp_path / "chat_rag_store.json.migrated").exists()
    finally:
        recall.close()

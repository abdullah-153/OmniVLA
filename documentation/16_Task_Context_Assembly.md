# Task-specific personal context

The planner and visual executor now receive only personal preferences and facts relevant to the current request. A request about a research report can retrieve its project folder without automatically adding an unrelated email account or browser. An empty query still provides the full profile overview for existing profile inspection.

`UserProfileMemory.build_context_pack(query)` returns the selected preferences, facts, successful workflows, and record references with source provenance. `get_planner_context(query)` produces a bounded model context from that pack. The plan message stores concise references, and the review card offers an expandable **Personal context supplied to the planner** section. This label describes what was supplied; it does not claim the model relied on every record.

The server now lets `run_planner_chat` perform model-assisted personal-context extraction when appropriate. It previously built a profile block first, which the planner replaced internally, making the server's work redundant and obscuring that learning path.

This is the first retrieval milestone. It uses deterministic token overlap and category hints, so synonyms and implicit relationships may still be missed. The next memory milestone should add stable project/person/document relationships, confidence and expiry, explicit correction handling, and a user-visible way to remove or edit individual records. Memory remains advisory and cannot authorize actions.

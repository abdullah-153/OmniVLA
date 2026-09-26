# Bounded local file reading

The planner can answer an explicit request to read or summarize a named text file without controlling a desktop application. It first discovers matching files. When exactly one supported file matches, `READ_LOCAL_FILE` may read only that exact path during the same planner request. Multiple matches require the user to choose; the agent must not select one arbitrarily.

Supported formats are UTF-8 text, Markdown, CSV, JSON, Python, and logs. Files over 256 KB, hidden or credential-like names, and unsupported formats are rejected. The planner sees at most 12,000 characters and a SHA-256 digest of the complete file bytes. The assistant's tool receipt stores that file digest separately from the fingerprint of the formatted result. A new read checks the file again rather than serving a cached excerpt.

File content is untrusted input. Its text is bounded and placed inside the planner's untrusted tool data block; tags within the document are escaped. The digest identifies the bytes read at that moment, not the current file state or the truth of its contents. This milestone is read-only: editing and sending files need separate reviewed actions and outcome checks.

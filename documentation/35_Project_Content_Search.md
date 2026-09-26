# Project content search

The planner can now use `SEARCH_LOCAL_TEXT` to answer questions from project
notes without knowing a filename. It is advertised when the current request
selects remembered project folders. Without a selected folder, the tool fails
explicitly and asks for project context; it never substitutes a global scan.

Search accepts one to eight distinctive words and looks for them in a nearby
three-line passage. It searches `.txt`, `.md`, `.csv`, `.json`, `.py`, and `.log`
files using the bounded local reader. Protected filenames, unsupported encodings,
oversized files, and detected file changes are skipped. Search returns at most
three passages with source path, starting line, excerpt, truncation flags, and
the SHA-256 of the file read. A single-match result also carries the file digest
in its persisted tool receipt. Discovered matches can be opened by the existing
file-read tool if more context is needed.

Limits: at most 60 candidates, depth five, a one-second discovery walk and a
three-second overall cooperative deadline, 256,000 bytes per readable file,
the first 12,000 characters per file, and 320 characters per excerpt. Cancellation
is checked between files and during passage scanning. OS reads themselves cannot
be interrupted. Coverage is always described as partial; no match cannot prove
the information is absent. This is keyword search, not semantic retrieval, and
does not cover PDFs, Office documents, OCR, or synonyms.

The tool uses the same planner budget, cancellation, receipts, and untrusted-data
rules as other personal tools. File text is escaped inside the result wrapper.
Remembered folder selection remains an advisory default, not a general OS
permission sandbox. Existing filesystem race limitations still apply.

Validation: 72 targeted tests pass, including scoped search, protected-file
exclusion, digest evidence, missing scope, cancellation, tool syntax, and planner
integration. `evaluate_project_memory.py` now accepts either a direct read or a
content-search read with the expected digest, and adds a case that specifically
requires the new tool. Network tools and notifications remain disabled during
that evaluation; it uses isolated memory and temporary files.

The live run on Spark-X2.5-4B Q4_K_M passed all four cases. Both unknown-filename
discovery and the explicit content-search request selected `SEARCH_LOCAL_TEXT`
and returned the expected file digest and status fact. The explicit content query
took 29.12 seconds in this run. This is a functional observation, not a controlled
latency benchmark or a broad retrieval-quality measurement. Results are stored in
`35_Local_Text_Search_Result.json`.

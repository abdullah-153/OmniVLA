# Tool receipts

Planner-side search, file discovery, web reading, and desktop notification calls now produce a bounded receipt for each request. The assistant message stores the tool name, returned success status, elapsed time, timestamp, and SHA-256 fingerprint of the tool's bounded text result. The tool arguments and full result are not copied into chat history by this mechanism; notification message bodies and searched file patterns therefore do not appear in the receipt.

The console displays receipts below the associated assistant response. Failed planner requests retain receipts for any calls that happened before the planner failed. Database loading normalizes receipt fields, limits each response to 12 receipts, and discards unexpected payload fields.

A receipt reports what the local tool returned. It is not a signed audit record or independent proof that a remote page is true, a file is still present, or a notification was seen by the user. Task completion must still follow the separate outcome verification contract.

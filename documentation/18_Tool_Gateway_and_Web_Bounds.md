# Planner tool gateway and bounded page reads

The existing planner tools now pass through `PersonalToolGateway`. It validates named arguments, returns a typed outcome with elapsed time, caches repeated read-only calls within one planner request, and avoids delivering the same successful notification twice during that request. A missing native notifier now reports failure rather than claiming a log message was displayed.

The webpage reader uses one bounded download path for extraction and fallback text parsing. It rejects non-HTTP schemes, credentials, local/private destinations, non-text responses, oversized pages, and redirects to disallowed destinations. It enforces request timeouts and a one-megabyte response limit. The planner labels retrieved material as untrusted data.

This is a foundation for future integrations, not a complete connector platform. DNS can change between validation and connection, so stronger network isolation or IP-pinned transport is required before accepting arbitrary untrusted URLs in a higher-risk deployment. Future tools should return durable receipts and declare permissions, side effects, and verification methods through the same gateway.

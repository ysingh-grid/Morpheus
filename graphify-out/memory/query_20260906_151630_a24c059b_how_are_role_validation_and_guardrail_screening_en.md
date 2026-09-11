---
type: "query"
date: "2026-09-06T15:16:30.381698+00:00"
question: "How are role validation and guardrail screening enforced across chat messages?"
contributor: "graphify"
source_nodes: ["_sanitize_messages(),_message_role(),chat_completions(),start_chat_workflow(),scan_user_input(),anonymize_pii()"]
---

# Q: How are role validation and guardrail screening enforced across chat messages?

## Answer

The gateway validates every message role, accepts only user, assistant, or system, requires the final message to be a user turn, sends every user-authored turn to the remote guardrail scanner, and performs local PII redaction only for assistant and system history.

## Source Nodes

- _sanitize_messages(),_message_role(),chat_completions(),start_chat_workflow(),scan_user_input(),anonymize_pii()
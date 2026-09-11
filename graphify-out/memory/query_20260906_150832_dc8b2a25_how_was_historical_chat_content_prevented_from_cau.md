---
type: "query"
date: "2026-09-06T15:08:32.408342+00:00"
question: "How was historical chat content prevented from causing guardrail denials?"
contributor: "graphify"
source_nodes: ["_sanitize_messages(),scan_user_input(),anonymize_pii(),test_message_history_is_redacted_locally_without_guardrail_rescan()"]
---

# Q: How was historical chat content prevented from causing guardrail denials?

## Answer

interfaces.openai_api._sanitize_messages now calls guardrails.scan_user_input only once, for messages[-1]. Every earlier message is passed only through guardrails.anonymize_pii before the workflow receives it. This prevents assistant responses and quoted document text from being sent to Groq again and blocking a later benign user turn, while preserving local redaction for the forwarded conversation history. A regression test verifies an assistant history message containing sinusitis and an email is redacted locally and that the cloud guardrail receives only the final user question.

## Source Nodes

- _sanitize_messages(),scan_user_input(),anonymize_pii(),test_message_history_is_redacted_locally_without_guardrail_rescan()
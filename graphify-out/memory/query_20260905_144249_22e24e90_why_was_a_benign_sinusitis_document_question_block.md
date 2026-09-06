---
type: "query"
date: "2026-09-05T14:42:49.213424+00:00"
question: "Why was a benign sinusitis document question blocked as confidential-data disclosure?"
contributor: "graphify"
source_nodes: ["_sanitize_messages(),scan_user_input(),Pipe.pipe()"]
---

# Q: Why was a benign sinusitis document question blocked as confidential-data disclosure?

## Answer

The benign latest prompt is classified safe when scanned alone. The false rejection occurs because interfaces.openai_api._sanitize_messages loops over the entire Open WebUI messages array, including prior assistant responses and document-derived context, and sends every message independently through both Groq guard models. Any older message flagged by GPT-OSS Safeguard aborts the new request with HTTP 400, making its category appear to belong to the latest prompt. The security classifier should evaluate the latest user-authored turn for blocking, while local PII redaction can be applied to user-authored history before forwarding; assistant/system history must not be reclassified as new user intent.

## Source Nodes

- _sanitize_messages(),scan_user_input(),Pipe.pipe()
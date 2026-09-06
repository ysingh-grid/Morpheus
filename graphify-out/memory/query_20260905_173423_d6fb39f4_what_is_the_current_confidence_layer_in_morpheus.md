---
type: "query"
date: "2026-09-05T17:34:23.794910+00:00"
question: "What is the current confidence layer in Morpheus?"
contributor: "graphify"
source_nodes: ["RetrievalConfidence,_assess_confidence(),scan_user_input(),verify_borderline_confidence_activity()"]
---

# Q: What is the current confidence layer in Morpheus?

## Answer

Morpheus has separate safety and retrieval gates. Safety uses Prompt Guard numeric risk >= 0.5 and then a GPT-OSS Safeguard binary violation/category decision; the safeguard stage has no calibrated confidence score, ensemble, or borderline review, so a single violation=1 blocks HTTP. Retrieval assesses the top hybrid-search candidate using RRF score >= 0.016, vector cosine distance <= 0.400, RRF margin >= 0.0002, lexical-match presence, and intent-specific table/figure/page structural evidence. Weak candidates become not_found; borderline candidates with lexical support become clarification_needed and may be checked by Gemini context sufficiency; strong candidates are grounded. FlashRank reranking occurs after the initial confidence decision.

## Source Nodes

- RetrievalConfidence,_assess_confidence(),scan_user_input(),verify_borderline_confidence_activity()
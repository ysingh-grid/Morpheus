---
type: "query"
date: "2026-09-05T17:39:00.789465+00:00"
question: "Are the current retrieval confidence thresholds too strict and should they be reduced?"
contributor: "graphify"
source_nodes: ["_assess_confidence(),_is_borderline_confidence(),RetrievalConfidence,evaluate()"]
---

# Q: Are the current retrieval confidence thresholds too strict and should they be reduced?

## Answer

The combined semantic gate is too brittle because RRF >= 0.016, vector distance <= 0.400, and margin >= 0.0002 effectively all must pass; without a lexical match, any failed signal becomes not_found. The 22-case verified benchmark reports 1.0 confidence accuracy but is small, while the 100-case unverified benchmark reports 0.5 and cannot establish production calibration. Recommended design is a band rather than blindly lowering every threshold: strong accept at current values; borderline verification for RRF 0.012-0.016 or vector distance 0.400-0.460; hard reject only beyond the weak band with no lexical or structural evidence. A low RRF margin should indicate ambiguity, not absence, and should route to reranking or Gemini sufficiency verification rather than not_found.

## Source Nodes

- _assess_confidence(),_is_borderline_confidence(),RetrievalConfidence,evaluate()
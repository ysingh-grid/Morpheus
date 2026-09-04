---
type: "query"
date: "2026-09-04T21:26:52.126903+00:00"
question: "Why is Morpheus not a general chatbot with optional document context and web search?"
contributor: "graphify"
source_nodes: ["planner_node()", "AgentWorkflow", "morpheus_rag_pipe.py"]
---

# Q: Why is Morpheus not a general chatbot with optional document context and web search?

## Answer

The current planner mandates local document retrieval on every new turn, treats insufficient evidence as not_found or clarification, and exposes web search as a fallback or explicit phrase route. It lacks a normal conversational answer branch and a planner that dynamically chooses among chat, document retrieval, and web tools. Uploaded documents should instead become optional session context, while an intent-aware planner selects zero or more tools per turn.

## Source Nodes

- planner_node()
- AgentWorkflow
- morpheus_rag_pipe.py
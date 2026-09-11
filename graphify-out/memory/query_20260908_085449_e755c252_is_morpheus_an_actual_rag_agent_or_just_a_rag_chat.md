---
type: "query"
date: "2026-09-08T08:54:49.887309+00:00"
question: "Is Morpheus an actual RAG agent or just a RAG chatbot?"
contributor: "graphify"
source_nodes: ["planner_node,compile_agent_graph,AgentWorkflow,AgentPlan,_planned_action"]
---

# Q: Is Morpheus an actual RAG agent or just a RAG chatbot?

## Answer

Morpheus is a bounded RAG agent, not a retrieve-then-generate chatbot. Gemini plans a tool sequence (zero or more of hybrid_search and registered MCP tools). Temporal loops: LangGraph decides one next_action, one activity executes it, then the graph runs again, up to 5 turns. It can skip retrieval for conversation, retrieve then verify groundedness, pause for HITL web-search approval, call MCP, or generate. LangGraph tool nodes are stubs; the ReAct loop lives in AgentWorkflow, not inside LangGraph. It is not an open-ended ReAct researcher: closed action set, 5-turn cap, no free-form tool invention.

## Source Nodes

- planner_node,compile_agent_graph,AgentWorkflow,AgentPlan,_planned_action
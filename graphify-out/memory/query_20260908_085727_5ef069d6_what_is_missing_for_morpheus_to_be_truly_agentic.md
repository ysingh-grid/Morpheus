---
type: "query"
date: "2026-09-08T08:57:27.394149+00:00"
question: "What is missing for Morpheus to be truly agentic?"
contributor: "graphify"
source_nodes: ["planner_node,_planned_action,AgentWorkflow,hybrid_search_node,registered_tool_specs"]
---

# Q: What is missing for Morpheus to be truly agentic?

## Answer

The core gap is observation-conditioned re-planning. Gemini writes tool_sequence once; later Temporal turns only walk remaining tools. LangGraph tool nodes are stubs and the planner never sees hydrated retrieval or MCP payloads, so it cannot rewrite a query, retry search, or pick a URL from Tavily to fetch. Also missing: multi-shot retrieval, general HITL questions (not just approve_web_search), agent-chosen memory writes, parallel tools, goal decomposition, self-critique that requests more evidence, and subagents. Production gaps (auth, OCR, pooling) are not what make it agentic.

## Source Nodes

- planner_node,_planned_action,AgentWorkflow,hybrid_search_node,registered_tool_specs
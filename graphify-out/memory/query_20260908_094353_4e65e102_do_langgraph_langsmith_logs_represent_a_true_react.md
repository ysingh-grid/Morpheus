---
type: "query"
date: "2026-09-08T09:43:53.501754+00:00"
question: "Do LangGraph/LangSmith logs represent a true ReAct agent or a Temporal workflow?"
contributor: "graphify"
source_nodes: ["run_agent_graph_activity,planner_node,compile_agent_graph,AgentWorkflow"]
---

# Q: Do LangGraph/LangSmith logs represent a true ReAct agent or a Temporal workflow?

## Answer

LangSmith shows each Temporal activity as a separate root trace. A LangGraph invoke is only load_history -> planner -> one stub node (mcp_search or synthesize_answer) then END. Tool execution and answer generation are sibling roots, not children of LangGraph. create_agent_plan can run again after a tool (replan), but that is Temporal looping activities, not a ReAct cycle inside LangGraph. The logs represent a durable workflow with a planner, not a true ReAct agent graph.

## Source Nodes

- run_agent_graph_activity,planner_node,compile_agent_graph,AgentWorkflow
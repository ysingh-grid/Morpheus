---
type: "query"
date: "2026-09-08T09:46:48.129167+00:00"
question: "How do I wrap an agent when created inside a Temporal loop?"
contributor: "graphify"
source_nodes: ["AgentWorkflow,run_agent_graph_activity,compile_agent_graph,run_worker"]
---

# Q: How do I wrap an agent when created inside a Temporal loop?

## Answer

Do not store the LangGraph object in the workflow. Compile the agent in the worker process. Temporal holds only JSON AgentState. The workflow while-loop is the durable ReAct outer loop: activity think (run_agent_graph_activity) then activity act (retrieval/MCP/answer) then write observation and loop. HITL is wait_condition plus signal. Creating compile_agent_graph() inside workflows.py is illegal because it is nondeterministic. Creating it inside each activity is allowed but wasteful; create once at worker import.

## Source Nodes

- AgentWorkflow,run_agent_graph_activity,compile_agent_graph,run_worker
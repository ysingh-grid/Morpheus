---
type: "query"
date: "2026-09-07T05:07:38.911840+00:00"
question: "How does clarification approval resume a Temporal agent workflow?"
contributor: "graphify"
source_nodes: ["AgentWorkflow.run(),AgentWorkflow.user_clarification_signal(),AgentWorkflow.get_workflow_state(),submit_clarification(),_workflow_state()"]
---

# Q: How does clarification approval resume a Temporal agent workflow?

## Answer

AgentWorkflow preserves state in awaiting_clarification for up to 24 hours. The gateway first confirms that status, then signals the workflow. Approval restores the plan with mcp_search available and resumes the bounded loop; cancellation or expiry produces a terminal answer without web search. Document-only not-found results remain terminal without a clarification wait.

## Source Nodes

- AgentWorkflow.run(),AgentWorkflow.user_clarification_signal(),AgentWorkflow.get_workflow_state(),submit_clarification(),_workflow_state()
"""Minimal Code Mode agent harness: the LLM sees ONE tool (run_code).

START -> agent -> (tools -> agent ... | END). Raw logs are only reachable
inside the runtime via the SDK — there is no read_log/grep tool that could
leak bloat into the context.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .config import USER_AGENT, load_settings
from .runner import SDK_DOC, TOOLS

SYSTEM_PROMPT = (
    "You debug a refresh-token race condition using Code Mode.\n"
    "You have exactly one tool: run_code(code). "
    "Never ask for raw file contents — there is no tool that returns them.\n"
    + SDK_DOC
    + "\nWrite ONE Python program that answers the user's multi-file question, "
    "run it, then report the findings in ≤10 lines."
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    input_tokens: int
    output_tokens: int


def make_llm(model: str, temp: float | None = None) -> ChatOpenAI:
    s = load_settings()
    # Go inference endpoint: *-contributor models only speak the responses
    # protocol -> force it here (same as B1).
    kwargs: dict = {
        "model": model,
        "use_responses_api": True,
        "default_headers": {"x-opencode-session": s.session_id, "User-Agent": USER_AGENT},
    }
    if temp is not None:
        kwargs["temperature"] = temp
    if s.api_key:
        kwargs["api_key"] = s.api_key
    if s.base_url:
        kwargs["base_url"] = s.base_url
    return ChatOpenAI(**kwargs)


def build_graph():
    s = load_settings()
    agent_llm = make_llm(s.agent_model).bind_tools(TOOLS)
    tool_node = ToolNode(TOOLS)

    def agent_node(state: AgentState) -> dict:
        resp = agent_llm.invoke([SystemMessage(content=SYSTEM_PROMPT)] + state["messages"])
        usage = getattr(resp, "usage_metadata", None) or {}
        return {
            "messages": [resp],
            "input_tokens": state.get("input_tokens", 0) + int(usage.get("input_tokens", 0) or 0),
            "output_tokens": state.get("output_tokens", 0) + int(usage.get("output_tokens", 0) or 0),
        }

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", "end": END})
    g.add_edge("tools", "agent")
    return g.compile()


def run_task(task: str, max_steps: int = 6) -> dict:
    """Drive the graph until the agent stops calling tools (or max_steps)."""
    app = build_graph()
    state: dict = {"messages": [HumanMessage(content=task)], "input_tokens": 0, "output_tokens": 0}
    for _ in range(max_steps):
        state = app.invoke(state)
        if not getattr(state["messages"][-1], "tool_calls", None):
            break
        state["messages"].append(HumanMessage(content="Continue: aggregate further or report findings."))
    return state

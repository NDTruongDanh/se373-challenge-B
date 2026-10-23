"""LangGraph agent harness with tool calls + conditional compaction.

Flow per invoke: START -> agent -> (tools -> compact -> END | compact -> END)
The driver (demo.py) re-invokes the graph for a few rounds to build a LONG
session; compaction replaces history via RemoveMessage so raw bloat leaves
the active context and only the checkpoint + short tail remain.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from .compaction import SYSTEM_PROMPT, compact_messages, total_input_tokens
from .config import ROOT, USER_AGENT, load_settings
from .tools import TOOLS


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    checkpoint_md: str
    compactions: int
    input_tokens: int
    output_tokens: int
    last_compact: dict  # stats of the most recent in-graph compaction


def make_llm(model: str, temp: float | None = None) -> ChatOpenAI:
    s = load_settings()
    # Go inference endpoint: *-contributor models only speak the responses
    # protocol -> force it here. Auth = Go API key; routing/caching =
    # client-chosen x-opencode-session; identification = own User-Agent
    # (https://opencode.ai/docs/go/#where-can-i-use-it).
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
    compact_llm = make_llm(s.compact_model) if s.has_key else None
    tool_node = ToolNode(TOOLS)
    budget = s.token_budget
    archive = ROOT / "archive" / "session_full.jsonl"

    def agent_node(state: AgentState) -> dict:
        call_msgs: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]
        if state.get("checkpoint_md"):
            call_msgs.append(SystemMessage(content="Active checkpoint (do NOT re-read raw logs):\n" + state["checkpoint_md"]))
        call_msgs += state["messages"]
        resp = agent_llm.invoke(call_msgs)
        usage = getattr(resp, "usage_metadata", None) or {}
        return {
            "messages": [resp],
            "input_tokens": state.get("input_tokens", 0) + int(usage.get("input_tokens", 0) or 0),
            "output_tokens": state.get("output_tokens", 0) + int(usage.get("output_tokens", 0) or 0),
        }

    def compact_node(state: AgentState) -> dict:
        msgs = state["messages"]
        if total_input_tokens(msgs) < budget:
            return {}
        # Ensure every message has an id so RemoveMessage can drop it.
        import uuid

        for m in msgs:
            if not getattr(m, "id", None):
                try:
                    m.id = f"msg_{uuid.uuid4().hex[:8]}"
                except Exception:
                    pass
        # Live runs fail loudly: an LLM summary error raises instead of
        # silently falling back (strict iff we actually have an LLM).
        new_msgs, _cp, stats = compact_messages(msgs, llm=compact_llm, archive_path=archive, strict=compact_llm is not None)
        md = new_msgs[0].content if isinstance(new_msgs[0].content, str) else str(new_msgs[0].content)
        print(f"[compact#{state.get('compactions', 0) + 1} via={stats['via']}] {stats['before_tokens']} -> {stats['after_tokens']} tokens (-{stats['reduction_pct']}%)")
        # Replace history: remove every current message id, then add compacted ones.
        removals = [RemoveMessage(id=m.id) for m in msgs if getattr(m, "id", None)]
        return {"messages": removals + new_msgs, "checkpoint_md": md, "compactions": state.get("compactions", 0) + 1, "last_compact": stats}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return "compact"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_node("compact", compact_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", "compact": "compact"})
    g.add_edge("tools", "compact")
    g.add_edge("compact", END)
    return g.compile()


def run_task(task: str, rounds: int = 4) -> dict:
    """Drive the graph for several rounds to build a LONG session.

    Each round re-invokes the compiled graph with the latest state, so the
    agent keeps calling tools (producing bloat) until it stops or rounds run out.
    """
    app = build_graph()
    state: dict = {
        "messages": [HumanMessage(content=task)],
        "checkpoint_md": "",
        "compactions": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "last_compact": {},
    }
    for _ in range(rounds):
        state = app.invoke(state)
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            break
        # Should not normally happen (tools always run before END), but if the
        # agent emitted tool calls that were never executed, nudge it forward.
        state["messages"].append(HumanMessage(content="Continue using tools until you state findings."))
    return state

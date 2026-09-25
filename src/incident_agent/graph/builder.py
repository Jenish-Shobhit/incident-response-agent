"""Wiring the eleven nodes together.

Three lines here are the difference between a graph that runs and a graph that fails at
the interesting moment, and none of them are obvious from the diagram:

``defer=True`` on ``collect`` -- without it the fan-in runs as soon as the *first*
investigator finishes, and the ledger is built from one branch out of three. The bug
looks like a model that missed something.

``recursion_limit`` in the config -- LangGraph's default is 25 supersteps. Three planner
rounds with a fan-out each, plus a verify/redraft cycle, reaches the mid-twenties on a
normal run. Leaving it at the default means the graph works in testing and throws
``GraphRecursionError`` on the run that has to be recorded.

``InMemorySaver`` -- ``interrupt()`` needs a checkpointer or the state is gone the moment
the run stops, and there is nothing to resume into.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from incident_agent import config
from incident_agent.graph.nodes import (
    approve,
    collect,
    dispatch,
    execute,
    guard,
    ingest,
    investigate,
    match_runbooks,
    render,
    resolve,
    route_verdict,
    triage,
    verify,
)
from incident_agent.graph.state import IncidentState

RECURSION_LIMIT = config.RECURSION_LIMIT


def build():
    g = StateGraph(IncidentState)

    g.add_node("ingest", ingest)
    g.add_node("guard", guard)
    g.add_node("triage", triage)
    g.add_node("investigate", investigate)
    g.add_node("collect", collect, defer=True)
    g.add_node("match_runbooks", match_runbooks)
    g.add_node("resolve", resolve)
    g.add_node("verify", verify)
    g.add_node("render", render)
    g.add_node("approve", approve)
    g.add_node("execute", execute)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "guard")
    g.add_edge("guard", "triage")

    # The planner either fans out to investigators, or closes the investigation.
    g.add_conditional_edges("triage", dispatch, ["investigate", "match_runbooks"])

    # Every investigator lands in collect, which waits for all of them.
    g.add_edge("investigate", "collect")

    # ...and control goes back to the planner. This edge is what makes it a loop rather
    # than a single fan-out: the planner sees what came back and decides again.
    g.add_edge("collect", "triage")

    g.add_edge("match_runbooks", "resolve")
    g.add_edge("resolve", "verify")

    # A failed verdict sends the run backwards -- to more investigation, or to a redraft.
    g.add_conditional_edges("verify", route_verdict, ["triage", "resolve", "render"])

    g.add_edge("render", "approve")
    g.add_edge("approve", "execute")
    g.add_edge("execute", END)

    return g


def compile_graph(checkpointer=None):
    return build().compile(checkpointer=checkpointer or InMemorySaver())


def run_config(thread_id):
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}


app_graph = compile_graph()


if __name__ == "__main__":
    print(app_graph.get_graph().draw_mermaid())

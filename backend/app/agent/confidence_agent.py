from typing import TypedDict, List, Dict, Any

from langgraph.graph import StateGraph, START, END


class ConfidenceState(TypedDict):
    records: List[Dict[str, Any]]
    scored_records: List[Dict[str, Any]]


def calculate_confidence(state: ConfidenceState):

    records = state["records"]

    scored_records = []

    for record in records:

        issues = record.get(
            "validation_issues",
            []
        )

        issue_count = len(issues)
        if issue_count == 0:

            confidence = 100

        elif issue_count == 1:

            confidence = 80

        elif issue_count == 2:

            confidence = 60

        else:

            confidence = max(
                20,
                100 - (issue_count * 20)
            )
        if confidence >= 95:

            status = "SYSTEM_APPROVED"

        else:

            status = "HUMAN_REVIEW"

        scored_record = record.copy()

        scored_record["confidence_score"] = confidence

        scored_record["confidence_status"] = status

        scored_records.append(
            scored_record
        )

    return {
        "scored_records": scored_records
    }
graph = StateGraph(
    ConfidenceState
)

graph.add_node(
    "calculate_confidence",
    calculate_confidence
)

graph.add_edge(
    START,
    "calculate_confidence"
)

graph.add_edge(
    "calculate_confidence",
    END
)

confidence_graph = graph.compile()
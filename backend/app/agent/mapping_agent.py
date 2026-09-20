import os
import json
from pathlib import Path
from typing import TypedDict, List, Dict, Any

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
BASE_DIR = Path(__file__).resolve().parents[3]
load_dotenv(BASE_DIR / ".env")


GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is missing. Please add it to the .env file."
    )
TARGET_COLUMNS = [
    "employee_id",
    "name",
    "email",
    "joining_date",
    "department",
    "phone",
    "salary",
    "location"
]


class MappingState(TypedDict):
    source_columns: List[str]
    target_columns: List[str]
    mappings: List[Dict[str, Any]]
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    api_key=GROQ_API_KEY
)
def mapping_agent(state: MappingState):

    source_columns = state["source_columns"]
    target_columns = state["target_columns"]

    prompt = f"""
You are an AI Data Migration Agent.

Your job is to map columns from an OLD employee system
to a NEW employee system.

SOURCE COLUMNS:
{source_columns}

NEW SYSTEM TARGET COLUMNS:
{target_columns}

Understand the meaning of each source column.

Do NOT depend only on exact spelling.

For example:

Emp ID -> employee_id
Employee Name -> name
Email Address -> email
Joining Date -> joining_date
Dept -> department
DOJ -> joining_date

If a source column does not have a suitable target,
use null.

Return ONLY valid JSON.

Required format:

[
  {{
    "source_column": "Emp ID",
    "target_column": "employee_id",
    "confidence": 98,
    "reason": "Emp ID represents the employee identifier"
  }}
]

Confidence must be between 0 and 100.

SOURCE COLUMNS:
{source_columns}

TARGET COLUMNS:
{target_columns}
"""

    response = llm.invoke(prompt)

    content = response.content.strip()
    content = content.replace("```json", "")
    content = content.replace("```", "")
    content = content.strip()

    try:
        mappings = json.loads(content)

    except json.JSONDecodeError:
        mappings = []

    return {
        "mappings": mappings
    }
graph = StateGraph(MappingState)

graph.add_node(
    "mapping_agent",
    mapping_agent
)

graph.add_edge(
    START,
    "mapping_agent"
)

graph.add_edge(
    "mapping_agent",
    END
)

mapping_graph = graph.compile()
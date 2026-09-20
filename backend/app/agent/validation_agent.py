import re
import math
from datetime import datetime
from typing import TypedDict, List, Dict, Any

from langgraph.graph import StateGraph, START, END


class ValidationState(TypedDict):
    records: List[Dict[str, Any]]
    validated_records: List[Dict[str, Any]]


def clean_value(value):
    if value is None:
        return ""

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""

    return value


def validate_date(value):
    """
    Validate common employee joining-date formats.
    """

    if not value:
        return False

    value = str(value).strip()

    date_formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%Y-%m-%d",
    ]

    for date_format in date_formats:

        try:
            datetime.strptime(
                value,
                date_format
            )

            return True

        except ValueError:
            continue

    return False


def clean_and_validate(state: ValidationState):

    records = state["records"]

    validated_records = []

    employee_ids = {}

    for record in records:

        employee_id = clean_value(
            record.get(
                "employee_id",
                ""
            )
        )

        employee_id = str(
            employee_id
        ).strip()

        if employee_id:

            employee_ids[employee_id] = (
                employee_ids.get(
                    employee_id,
                    0
                ) + 1
            )

    for record in records:

        cleaned = {}
        for key, value in record.items():

            value = clean_value(value)

            if isinstance(value, str):

                value = value.strip()

            cleaned[key] = value

        issues = []

        employee_id = str(
            cleaned.get(
                "employee_id",
                ""
            )
        ).strip()

        if not employee_id:

            issues.append(
                "Missing Employee ID"
            )

        elif employee_ids.get(
            employee_id,
            0
        ) > 1:

            issues.append(
                "Duplicate Employee ID"
            )

        name = str(
            cleaned.get(
                "name",
                ""
            )
        ).strip()

        if not name:

            issues.append(
                "Missing Employee Name"
            )

        email = str(
            cleaned.get(
                "email",
                ""
            )
        ).strip()

        if not email:

            issues.append(
                "Missing Email"
            )

        else:

            email_pattern = (
                r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
            )

            if not re.match(
                email_pattern,
                email
            ):

                issues.append(
                    "Invalid Email"
                )

        joining_date = clean_value(
            cleaned.get(
                "joining_date",
                ""
            )
        )

        joining_date = str(
            joining_date
        ).strip()

        if not joining_date:

            issues.append(
                "Missing Joining Date"
            )

        elif not validate_date(
            joining_date
        ):

            issues.append(
                "Invalid Joining Date"
            )

        department = str(
            cleaned.get(
                "department",
                ""
            )
        ).strip()

        if not department:

            issues.append(
                "Missing Department"
            )

        if len(issues) == 0:

            validation_status = "VALID"

        else:

            validation_status = "INVALID"

        cleaned["validation_status"] = (
            validation_status
        )

        cleaned["validation_issues"] = (
            issues
        )

        validated_records.append(
            cleaned
        )

    return {
        "validated_records": validated_records
    }

graph = StateGraph(
    ValidationState
)

graph.add_node(
    "clean_and_validate",
    clean_and_validate
)

graph.add_edge(
    START,
    "clean_and_validate"
)

graph.add_edge(
    "clean_and_validate",
    END
)

validation_graph = graph.compile()
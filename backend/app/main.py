from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import List, Dict, Any
from pathlib import Path
from io import BytesIO
from datetime import datetime
import json

import pandas as pd

from app.agent.mapping_agent import (
    mapping_graph,
    TARGET_COLUMNS
)

from app.agent.validation_agent import (
    validation_graph
)

from app.agent.confidence_agent import confidence_graph


app = FastAPI(title="AI Data Migration Agent")
PROJECT_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = PROJECT_DIR / "data/uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = PROJECT_DIR / "data/results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_FILE = RESULTS_DIR / "migration_results.json"
REVIEW_FILE = RESULTS_DIR / "migration_review.json"
TARGET_FILE = RESULTS_DIR / "target_employees.json"
MAX_RETRY_ATTEMPTS = 2

if not TARGET_FILE.exists():
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "employees": [
                {
                    "employee_id": "102",
                    "name": "Existing Target Employee",
                    "email": "existing@example.com",
                    "joining_date": "01/01/2025",
                    "department": "Operations",
                    "phone": "",
                    "salary": "",
                    "location": ""
                }
            ]
        }, f, indent=4)


def read_results():
    source_file = REVIEW_FILE if REVIEW_FILE.exists() else RESULTS_FILE
    if not source_file.exists() or source_file.stat().st_size == 0:
        return {"status": "success", "message": "Migration results", "files": []}
    with open(source_file, "r", encoding="utf-8") as f:
        return json.load(f)


def read_target_data():
    empty_target = {"employees": []}
    try:
        if not TARGET_FILE.exists() or TARGET_FILE.stat().st_size == 0:
            with open(TARGET_FILE, "w", encoding="utf-8") as f:
                json.dump(empty_target, f, indent=4)
            return empty_target

        with open(TARGET_FILE, "r", encoding="utf-8") as f:
            target_data = json.load(f)

        if not isinstance(target_data, dict) or not isinstance(target_data.get("employees"), list):
            raise ValueError("Invalid target employee structure")
        return target_data
    except (json.JSONDecodeError, OSError, ValueError):
        with open(TARGET_FILE, "w", encoding="utf-8") as f:
            json.dump(empty_target, f, indent=4)
        return empty_target


def save_results(results_data):
    persisted_files = []
    persisted_fields = [
        "record_id",
        "employee_id",
        "name",
        "email",
        "joining_date",
        "department",
        "phone",
        "salary",
        "location",
        "validation_status",
        "validation_issues",
        "confidence_score",
        "confidence_status",
        "approval_source",
        "human_review_status",
        "approved_by",
        "migration_status",
        "migration_attempts",
        "migration_error",
        "duplicate_group_id",
        "duplicate_status",
        "duplicate_retry_required",
        "duplicate_resolution_reason",
        "resolved_by",
        "resolved_at",
        "migrated_at",
        "rollback_at",
        "escalation_status"
    ]

    for file_data in results_data.get("files", []):
        persisted_records = []
        for record in file_data.get("records", []):
            persisted_record = {
                field: record.get(field)
                for field in persisted_fields
                if field in record
            }
            if "approval_source" not in persisted_record:
                persisted_record["approval_source"] = (
                    "HUMAN"
                    if record.get("duplicate_status") == "KEPT"
                    else "SYSTEM"
                    if record.get("confidence_status") == "SYSTEM_APPROVED"
                    else "HUMAN_REVIEW"
                )
            if "human_review_status" not in persisted_record:
                persisted_record["human_review_status"] = (
                    "RESOLVED"
                    if record.get("approval_source") == "HUMAN"
                    else "NOT_REQUIRED"
                    if record.get("confidence_status") == "SYSTEM_APPROVED"
                    else "PENDING"
                )
            if "approved_by" not in persisted_record:
                persisted_record["approved_by"] = (
                    record.get("approval_source")
                    if record.get("confidence_status") == "SYSTEM_APPROVED"
                    else None
                )
            if record.get("duplicate_status") == "REMOVED":
                persisted_record["migration_status"] = "REMOVED"
            persisted_records.append(persisted_record)

        persisted_files.append({
            "file_name": file_data.get("file_name"),
            "records": persisted_records
        })

    compact_results = {
        "status": results_data.get("status", "success"),
        "message": "Migration result audit",
        "files": persisted_files
    }

    approved_results = {
        "status": results_data.get("status", "success"),
        "message": "Approved migration result audit",
        "files": [
            {
                "file_name": file_data["file_name"],
                "records": [
                    record
                    for record in file_data["records"]
                    if record.get("confidence_score") == 100
                    and record.get("confidence_status") == "SYSTEM_APPROVED"
                    and record.get("approval_source") in ["SYSTEM", "HUMAN"]
                ]
            }
            for file_data in persisted_files
        ]
    }

    with open(REVIEW_FILE, "w", encoding="utf-8") as f:
        json.dump(compact_results, f, indent=4, default=str)

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(approved_results, f, indent=4, default=str)


def revalidate_records(records):
    active_records = [record for record in records if record.get("duplicate_status") != "REMOVED"]
    validation_result = validation_graph.invoke({"records": active_records, "validated_records": []})
    confidence_result = confidence_graph.invoke({"records": validation_result["validated_records"], "scored_records": []})
    scored_by_id = {record.get("record_id"): record for record in confidence_result["scored_records"]}
    target_ids = {
        str(employee.get("employee_id", "")).strip()
        for employee in read_target_data().get("employees", [])
    }
    for record in records:
        if record.get("duplicate_status") == "REMOVED":
            record["confidence_status"] = "HUMAN_REVIEW"
            record["validation_status"] = "INVALID"
            record["validation_issues"] = ["Duplicate record removed"]
            continue
        updated = scored_by_id.get(record.get("record_id"))
        if updated:
            record.clear()
            record.update(updated)
            employee_id = str(record.get("employee_id", "")).strip()
            if employee_id and employee_id in target_ids:
                issues = record.setdefault("validation_issues", [])
                if "Employee ID already exists in target system" not in issues:
                    issues.append("Employee ID already exists in target system")
                record["validation_status"] = "INVALID"
                record["confidence_score"] = 80
                record["confidence_status"] = "HUMAN_REVIEW"
                record["approval_source"] = "HUMAN_REVIEW"
                record["human_review_status"] = "PENDING"
                record["approved_by"] = None
            record["approval_source"] = (
                "HUMAN"
                if record.get("duplicate_status") == "KEPT"
                or record.get("human_review_status") == "RESOLVED"
                else "SYSTEM"
                if record.get("confidence_status") == "SYSTEM_APPROVED"
                else "HUMAN_REVIEW"
            )
            record["human_review_status"] = (
                "RESOLVED"
                if record.get("approval_source") == "HUMAN"
                else "NOT_REQUIRED"
                if record.get("confidence_status") == "SYSTEM_APPROVED"
                else "PENDING"
            )
            record["approved_by"] = (
                record["approval_source"]
                if record.get("confidence_status") == "SYSTEM_APPROVED"
                else None
            )


def add_duplicate_metadata(records):
    grouped = {}
    for record in records:
        employee_id = str(record.get("employee_id", "")).strip()
        if employee_id:
            grouped.setdefault(employee_id, []).append(record)
    for employee_id, group in grouped.items():
        for record in group:
            record["duplicate_group_id"] = f"DUP-{employee_id}" if len(group) > 1 else None
            record["duplicate_status"] = "PENDING_REVIEW" if len(group) > 1 else None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reset-results")
async def reset_results():
    for result_file in [RESULTS_FILE, REVIEW_FILE]:
        if result_file.exists():
            result_file.unlink()

    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        json.dump({"employees": []}, f, indent=4)

    return {"status": "success", "message": "Migration and target data cleared"}


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    results = []
    for file in files:
        filename = file.filename
        extension = Path(filename).suffix.lower()
        if extension not in [".csv", ".xlsx"]:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")
        content = await file.read()
        with open(UPLOAD_DIR / filename, "wb") as f:
            f.write(content)
        if extension == ".csv":
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content), engine="openpyxl")
        results.append({
            "file_name": filename,
            "file_type": extension,
            "rows": len(df),
            "columns": [str(column) for column in df.columns]
        })
    return {"status": "success", "message": "Files uploaded successfully", "files": results}


# =========================================================
# STEP 3 - AI MAPPING
# =========================================================

@app.post("/analyze-mapping")
async def analyze_mapping(
    files: List[UploadFile] = File(...)
):

    all_results = []

    for file in files:

        filename = file.filename

        extension = Path(
            filename
        ).suffix.lower()

        if extension not in [
            ".csv",
            ".xlsx"
        ]:

            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {filename}"
            )

        content = await file.read()

        if extension == ".csv":

            df = pd.read_csv(
                BytesIO(content)
            )

        else:

            df = pd.read_excel(
                BytesIO(content),
                engine="openpyxl"
            )

        source_columns = [
            str(column)
            for column in df.columns
        ]

        result = mapping_graph.invoke({

            "source_columns":
                source_columns,

            "target_columns":
                TARGET_COLUMNS,

            "mappings":
                []

        })

        all_results.append({

            "file_name":
                filename,

            "mappings":
                result["mappings"]

        })

    return {

        "status":
            "success",

        "message":
            "AI column mapping completed",

        "target_columns":
            TARGET_COLUMNS,

        "files":
            all_results
    }


# =========================================================
# STEP 4 + STEP 5
# MAPPING → CLEANING → VALIDATION → CONFIDENCE
# =========================================================

@app.post("/validate-data")
async def validate_data(files: List[UploadFile] = File(...)):
    all_records = []
    file_records = []

    for file in files:
        filename = file.filename
        extension = Path(filename).suffix.lower()
        if extension not in [".csv", ".xlsx"]:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

        content = await file.read()
        if extension == ".csv":
            df = pd.read_csv(BytesIO(content))
        else:
            df = pd.read_excel(BytesIO(content), engine="openpyxl")

        source_columns = [str(column) for column in df.columns]
        mapping_result = mapping_graph.invoke({
            "source_columns": source_columns,
            "target_columns": TARGET_COLUMNS,
            "mappings": []
        })
        mappings = mapping_result["mappings"]
        records = []
        for row_index, (_, row) in enumerate(df.iterrows(), start=2):
            target_record = {
                "record_id": f"{filename}:{row_index}",
                "migration_status": "PENDING",
                "employee_id": "",
                "name": "",
                "email": "",
                "joining_date": "",
                "department": "",
                "phone": "",
                "salary": "",
                "location": "",
                "migration_attempts": 0,
                "migration_error": None
            }
            for mapping in mappings:
                source_column = mapping.get("source_column")
                target_column = mapping.get("target_column")
                if source_column and target_column and source_column in df.columns:
                    target_record[target_column] = row[source_column]
            records.append(target_record)
            all_records.append(target_record)
        file_records.append((filename, mappings, records))

    add_duplicate_metadata(all_records)
    revalidate_records(all_records)
    all_results = [
        {"file_name": filename, "mappings": mappings, "records": records}
        for filename, mappings, records in file_records
    ]
    final_results = {
        "status": "success",
        "message": "AI mapping, cleaning, validation and confidence scoring completed",
        "files": all_results
    }
    save_results(final_results)

    for record in all_records:
        if record.get("confidence_status") != "SYSTEM_APPROVED":
            continue
        try:
            await create_target_employee(record)
            record["migration_status"] = "MIGRATED"
            record["migration_error"] = None
            record["migrated_at"] = datetime.now().isoformat()
        except HTTPException as error:
            record["migration_status"] = "FAILED"
            record["migration_error"] = error.detail
        except Exception as error:
            record["migration_status"] = "FAILED"
            record["migration_error"] = str(error)

    save_results(final_results)
    return final_results


async def legacy_validate_data(
    files: List[UploadFile] = File(...)
):

    all_results = []

    for file in files:

        filename = file.filename

        extension = Path(
            filename
        ).suffix.lower()

        if extension not in [
            ".csv",
            ".xlsx"
        ]:

            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {filename}"
            )

        content = await file.read()

        # -----------------------------------------
        # Read source file
        # -----------------------------------------

        if extension == ".csv":

            df = pd.read_csv(
                BytesIO(content)
            )

        else:

            df = pd.read_excel(
                BytesIO(content),
                engine="openpyxl"
            )

        # -----------------------------------------
        # Source columns
        # -----------------------------------------

        source_columns = [
            str(column)
            for column in df.columns
        ]

        # -----------------------------------------
        # AI Mapping
        # -----------------------------------------

        mapping_result = mapping_graph.invoke({

            "source_columns":
                source_columns,

            "target_columns":
                TARGET_COLUMNS,

            "mappings":
                []

        })

        mappings = mapping_result[
            "mappings"
        ]

        # -----------------------------------------
        # Convert source → target
        # -----------------------------------------

        target_records = []

        for _, row in df.iterrows():

            target_record = {}

            for mapping in mappings:

                source_column = mapping.get(
                    "source_column"
                )

                target_column = mapping.get(
                    "target_column"
                )

                if (
                    source_column
                    and target_column
                    and source_column in df.columns
                ):

                    target_record[
                        target_column
                    ] = row[
                        source_column
                    ]

            target_records.append(
                target_record
            )

        # -----------------------------------------
        # Cleaning + Validation
        # -----------------------------------------

        validation_result = (
            validation_graph.invoke({

                "records":
                    target_records,

                "validated_records":
                    []

            })
        )

        validated_records = (
            validation_result[
                "validated_records"
            ]
        )

        # -----------------------------------------
        # Confidence
        # -----------------------------------------

        confidence_result = (
            confidence_graph.invoke({

                "records":
                    validated_records,

                "scored_records":
                    []

            })
        )

        scored_records = (
            confidence_result[
                "scored_records"
            ]
        )

        all_results.append({

            "file_name":
                filename,

            "mappings":
                mappings,

            "records":
                scored_records

        })

    # =====================================================
    # SAVE RESULTS
    # =====================================================

    final_results = {

        "status":
            "success",

        "message":
            "AI mapping, cleaning, validation and confidence scoring completed",

        "files":
            all_results

    }

    with open(
        RESULTS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            final_results,
            f,
            indent=4,
            default=str
        )

    return final_results


# =========================================================
# STEP 6 - HUMAN REVIEW + RETRY
# =========================================================

@app.post("/retry-record")
async def retry_record(
    record: Dict[str, Any]
):

    record_id = record.get("record_id")
    if not record_id:
        raise HTTPException(status_code=400, detail="record_id is required")

    results_data = read_results()
    target_record = None
    all_records = []
    for file_data in results_data.get("files", []):
        all_records.extend(file_data.get("records", []))
        for existing_record in file_data.get("records", []):
            if existing_record.get("record_id") == record_id:
                target_record = existing_record

    if target_record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    retry_attempts = int(target_record.get("migration_attempts", 0) or 0) + 1
    if retry_attempts > MAX_RETRY_ATTEMPTS:
        target_record["escalation_status"] = "ESCALATED"
        save_results(results_data)
        raise HTTPException(
            status_code=409,
            detail="Record reached the maximum retry limit and requires escalation"
        )

    preserved = {
        key: target_record.get(key)
        for key in ["record_id", "duplicate_group_id", "duplicate_status", "migration_attempts"]
    }
    target_record.clear()
    target_record.update(record)
    target_record.update({key: value for key, value in preserved.items() if value is not None})
    target_record["migration_status"] = "PENDING"
    target_record["migration_error"] = None
    target_record["migration_attempts"] = retry_attempts
    target_record["duplicate_retry_required"] = False
    target_record["human_review_status"] = "RESOLVED"
    revalidate_records(all_records)
    if target_record.get("confidence_status") != "SYSTEM_APPROVED" and retry_attempts >= MAX_RETRY_ATTEMPTS:
        target_record["escalation_status"] = "ESCALATED"
        target_record.setdefault("validation_issues", []).append(
            "Record failed validation twice and requires escalation"
        )
    save_results(results_data)

    updated_record = target_record
    is_approved = (
        updated_record.get("confidence_score") == 100
        and updated_record.get("confidence_status") == "SYSTEM_APPROVED"
    )

    if is_approved:
        try:
            await create_target_employee(updated_record)
            updated_record["migration_status"] = "MIGRATED"
            updated_record["migration_error"] = None
            updated_record["migrated_at"] = datetime.now().isoformat()
            save_results(results_data)
        except HTTPException as error:
            updated_record["migration_status"] = "FAILED"
            updated_record["migration_error"] = error.detail
            save_results(results_data)

    return {

        "status":
            "success",

        "record":
            updated_record,

        "saved_to_migration_results":
            is_approved,

        "message":
            "Record validated and saved to migration_results.json"
            if is_approved
            else "Record revalidated and saved for human review"

    }


@app.post("/resolve-duplicate")
async def resolve_duplicate(payload: Dict[str, Any]):
    keep_record_id = payload.get("keep_record_id")
    if not keep_record_id:
        raise HTTPException(status_code=400, detail="keep_record_id is required")

    results_data = read_results()
    all_records = []
    kept_record = None
    group_id = None
    for file_data in results_data.get("files", []):
        for existing_record in file_data.get("records", []):
            all_records.append(existing_record)
            if existing_record.get("record_id") == keep_record_id:
                kept_record = existing_record
                group_id = existing_record.get("duplicate_group_id")

    if kept_record is None or not group_id:
        raise HTTPException(status_code=404, detail="Duplicate record group not found")

    resolved_at = datetime.now().isoformat()
    removed = []
    for existing_record in all_records:
        if existing_record.get("duplicate_group_id") != group_id:
            continue
        if existing_record.get("record_id") == keep_record_id:
            existing_record["duplicate_status"] = "KEPT"
            existing_record["duplicate_retry_required"] = True
            existing_record["confidence_status"] = "HUMAN_REVIEW"
            existing_record["approval_source"] = "HUMAN_REVIEW"
            existing_record["human_review_status"] = "PENDING"
            existing_record["approved_by"] = None
            existing_record["validation_issues"] = [
                "Duplicate resolved. Retry required."
            ]
        else:
            existing_record["duplicate_status"] = "REMOVED"
            existing_record["duplicate_resolution_reason"] = "Duplicate resolution"
            existing_record["resolved_by"] = "Human"
            existing_record["resolved_at"] = resolved_at
            existing_record["migration_status"] = "REMOVED"
            removed.append(existing_record.get("record_id"))

    save_results(results_data)
    return {
        "status": "success",
        "message": "Duplicate resolved and records revalidated",
        "kept_record_id": keep_record_id,
        "removed_record_ids": removed,
        "record": kept_record
    }


# =========================================================
# STEP 7 - MOCK TARGET API
# =========================================================

@app.get("/target/employees")
async def list_target_employees():
    return read_target_data()


@app.delete("/target/employees/{employee_id}")
async def delete_target_employee(employee_id: str):
    target_data = read_target_data()

    employees = target_data.get("employees", [])
    original_count = len(employees)
    target_data["employees"] = [
        employee
        for employee in employees
        if str(employee.get("employee_id", "")).strip() != str(employee_id).strip()
    ]

    if len(target_data["employees"]) == original_count:
        raise HTTPException(status_code=404, detail="Target employee not found")

    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        json.dump(target_data, f, indent=4, default=str)

    return {
        "status": "success",
        "message": f"Target employee {employee_id} deleted"
    }


@app.post("/target/employees")
async def create_target_employee(
    employee: Dict[str, Any]
):

    employee_id = str(
        employee.get(
            "employee_id",
            ""
        )
    ).strip()

    # -----------------------------------------
    # Employee ID is required
    # -----------------------------------------

    if not employee_id:

        raise HTTPException(
            status_code=400,
            detail="Employee ID is required"
        )

    # -----------------------------------------
    # Read target system
    # -----------------------------------------

    target_data = read_target_data()

    employees = target_data.get(
        "employees",
        []
    )

    # -----------------------------------------
    # Check duplicate in target system
    # -----------------------------------------

    for existing_employee in employees:

        existing_id = str(
            existing_employee.get(
                "employee_id",
                ""
            )
        ).strip()

        if existing_id == employee_id:

            raise HTTPException(
                status_code=409,
                detail=(
                    f"Employee ID {employee_id} "
                    "already exists in target system"
                )
            )

    # -----------------------------------------
    # Add employee
    # -----------------------------------------

    employee_to_store = {
        key: employee.get(key, "")
        for key in [
            "employee_id",
            "name",
            "email",
            "joining_date",
            "department",
            "phone",
            "salary",
            "location"
        ]
    }

    employees.append(
        employee_to_store
    )

    target_data["employees"] = employees

    # -----------------------------------------
    # Save target system
    # -----------------------------------------

    with open(
        TARGET_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            target_data,
            f,
            indent=4,
            default=str
        )

    return {

        "status":
            "success",

        "message":
            "Employee created successfully",

        "employee":
            employee_to_store

    }


# =========================================================
# STEP 7 - MIGRATE APPROVED RECORDS
# =========================================================

@app.post("/migrate")
async def migrate_records():

    # -----------------------------------------
    # Check migration results
    # -----------------------------------------

    if not RESULTS_FILE.exists():

        raise HTTPException(
            status_code=404,
            detail="No migration results found. Run AI analysis first."
        )

    # -----------------------------------------
    # Read results
    # -----------------------------------------

    with open(
        RESULTS_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        results_data = json.load(f)

    migration_summary = []

    # -----------------------------------------
    # Process every file
    # -----------------------------------------

    for file_data in results_data.get(
        "files",
        []
    ):

        filename = file_data.get(
            "file_name"
        )

        records = file_data.get(
            "records",
            []
        )

        # -----------------------------------------
        # Process every record
        # -----------------------------------------

        for index, record in enumerate(
            records
        ):

            if record.get("duplicate_status") == "REMOVED":
                record["migration_status"] = "REMOVED"
                migration_summary.append({
                    "file_name": filename,
                    "record_id": record.get("record_id"),
                    "employee_id": record.get("employee_id"),
                    "status": "SKIPPED",
                    "reason": "Duplicate record removed"
                })
                continue

            confidence_status = record.get(
                "confidence_status",
                "HUMAN_REVIEW"
            )

            # ---------------------------------
            # Only approved records migrate
            # ---------------------------------

            if confidence_status != "SYSTEM_APPROVED":

                record["migration_status"] = (
                    "WAITING_FOR_HUMAN_REVIEW"
                )

                migration_summary.append({

                    "file_name":
                        filename,

                    "record":
                        index + 1,

                    "employee_id":
                        record.get(
                            "employee_id"
                        ),

                    "status":
                        "SKIPPED",

                    "reason":
                        "Record requires human review"

                })

                continue

            # ---------------------------------
            # Already migrated
            # ---------------------------------

            if record.get(
                "migration_status"
            ) == "MIGRATED":

                migration_summary.append({

                    "file_name":
                        filename,

                    "record":
                        index + 1,

                    "employee_id":
                        record.get(
                            "employee_id"
                        ),

                    "status":
                        "ALREADY_MIGRATED"

                })

                continue

            # ---------------------------------
            # Migration attempt
            # ---------------------------------

            attempts = record.get(
                "migration_attempts",
                0
            )

            attempts += 1

            record[
                "migration_attempts"
            ] = attempts

            try:

                # ---------------------------------
                # Store in mock target system
                # ---------------------------------

                target_response = (
                    await create_target_employee(
                        record
                    )
                )

                record[
                    "migration_status"
                ] = "MIGRATED"

                record[
                    "migration_error"
                ] = None

                record[
                    "migrated_at"
                ] = datetime.now().isoformat()

                migration_summary.append({

                    "file_name":
                        filename,

                    "record":
                        index + 1,

                    "employee_id":
                        record.get(
                            "employee_id"
                        ),

                    "status":
                        "SUCCESS",

                    "message":
                        target_response[
                            "message"
                        ]

                })

            except HTTPException as error:

                record[
                    "migration_status"
                ] = "FAILED"

                record[
                    "migration_error"
                ] = error.detail

                migration_summary.append({

                    "file_name":
                        filename,

                    "record":
                        index + 1,

                    "employee_id":
                        record.get(
                            "employee_id"
                        ),

                    "status":
                        "FAILED",

                    "error":
                        error.detail

                })

            except Exception as error:

                record[
                    "migration_status"
                ] = "FAILED"

                record[
                    "migration_error"
                ] = str(error)

                migration_summary.append({

                    "file_name":
                        filename,

                    "record":
                        index + 1,

                    "employee_id":
                        record.get(
                            "employee_id"
                        ),

                    "status":
                        "FAILED",

                    "error":
                        str(error)

                })

    # -----------------------------------------
    # Save migration results
    # -----------------------------------------

    with open(
        RESULTS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results_data,
            f,
            indent=4,
            default=str
        )

    # -----------------------------------------
    # Summary
    # -----------------------------------------

    successful = sum(
        1
        for item in migration_summary
        if item["status"] == "SUCCESS"
    )

    failed = sum(
        1
        for item in migration_summary
        if item["status"] == "FAILED"
    )

    skipped = sum(
        1
        for item in migration_summary
        if item["status"] == "SKIPPED"
    )

    return {

        "status":
            "success",

        "message":
            "Migration process completed",

        "summary": {

            "successful":
                successful,

            "failed":
                failed,

            "skipped":
                skipped

        },

        "records":
            migration_summary

    }

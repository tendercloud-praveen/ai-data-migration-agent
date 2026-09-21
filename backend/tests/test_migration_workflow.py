import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


os.environ.setdefault("GROQ_API_KEY", "test-key")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app import main


class MigrationWorkflowTests(unittest.TestCase):
    def test_reconciliation_fills_only_agreed_missing_values(self):
        records = [
            {"record_id": "a.csv:2", "employee_id": "7", "name": "Ana", "email": ""},
            {"record_id": "b.csv:2", "employee_id": "7", "name": "Ana", "email": "ana@example.com"},
        ]

        main.reconcile_records(records)

        self.assertEqual(records[0]["email"], "ana@example.com")

    def test_reconciliation_does_not_choose_conflicting_values(self):
        records = [
            {"record_id": "a.csv:2", "employee_id": "8", "name": "Ana"},
            {"record_id": "b.csv:2", "employee_id": "8", "name": "Anna"},
        ]

        main.reconcile_records(records)

        self.assertEqual(records[0]["name"], "Ana")
        self.assertEqual(records[1]["name"], "Anna")

    def test_duplicate_metadata_groups_records_by_employee_id(self):
        records = [
            {"record_id": "a.csv:2", "employee_id": "101"},
            {"record_id": "b.csv:6", "employee_id": "101"},
            {"record_id": "b.csv:7", "employee_id": "102"},
        ]

        main.add_duplicate_metadata(records)

        self.assertEqual(records[0]["duplicate_group_id"], "DUP-101")
        self.assertEqual(records[1]["duplicate_status"], "PENDING_REVIEW")
        self.assertIsNone(records[2]["duplicate_group_id"])

    def test_target_conflict_forces_human_review(self):
        record = {
            "record_id": "source.csv:2",
            "employee_id": "101",
            "name": "New Name",
            "email": "new@example.com",
        }
        validation = {"validated_records": [record.copy()]}
        confidence = {
            "scored_records": [{
                **record,
                "validation_status": "VALID",
                "validation_issues": [],
                "confidence_score": 100,
                "confidence_status": "SYSTEM_APPROVED",
            }]
        }

        with patch.object(main, "read_target_data", return_value={"employees": [{"employee_id": "101"}]}), \
             patch.object(main.validation_graph, "invoke", return_value=validation), \
             patch.object(main.confidence_graph, "invoke", return_value=confidence):
            main.revalidate_records([record])

        self.assertEqual(record["confidence_status"], "HUMAN_REVIEW")
        self.assertIn("Employee ID already exists in target system", record["validation_issues"])

    def test_retry_after_limit_stays_escalated_in_human_review(self):
        record = {
            "record_id": "source.csv:2",
            "employee_id": "999",
            "name": "Needs Review",
            "migration_attempts": main.MAX_RETRY_ATTEMPTS,
        }
        results = {"files": [{"file_name": "source.csv", "records": [record]}]}
        confidence = {
            "scored_records": [{
                **record,
                "validation_status": "INVALID",
                "validation_issues": ["Invalid value"],
                "confidence_score": 80,
                "confidence_status": "HUMAN_REVIEW",
            }]
        }

        with patch.object(main, "read_results", return_value=results), \
             patch.object(main, "save_results"), \
             patch.object(main.validation_graph, "invoke", return_value={"validated_records": [record]}), \
             patch.object(main.confidence_graph, "invoke", return_value=confidence):
            import asyncio
            response = asyncio.run(main.retry_record(record.copy()))

        self.assertEqual(response["record"]["confidence_status"], "HUMAN_REVIEW")
        self.assertEqual(response["record"]["escalation_status"], "ESCALATED")

    def test_resolved_duplicate_retry_becomes_approved_and_migrated(self):
        record = {
            "record_id": "source.csv:2",
            "employee_id": "999",
            "name": "Approved Duplicate",
            "duplicate_group_id": "DUP-999",
            "duplicate_status": "KEPT",
            "duplicate_retry_required": True,
        }
        results = {"files": [{"file_name": "source.csv", "records": [record]}]}
        confidence_record = {
            **record,
            "validation_status": "VALID",
            "validation_issues": [],
            "confidence_score": 100,
            "confidence_status": "SYSTEM_APPROVED",
        }

        with patch.object(main, "read_results", return_value=results), \
             patch.object(main, "save_results"), \
             patch.object(main.validation_graph, "invoke", return_value={"validated_records": [record]}), \
             patch.object(main.confidence_graph, "invoke", return_value={"scored_records": [confidence_record]}), \
             patch.object(main, "create_target_employee", new_callable=AsyncMock):
            import asyncio
            response = asyncio.run(main.retry_record(record.copy()))

        self.assertEqual(response["record"]["confidence_status"], "SYSTEM_APPROVED")
        self.assertEqual(response["record"]["migration_status"], "MIGRATED")
        self.assertTrue(response["saved_to_migration_results"])

    def test_reset_results_preserves_only_designated_target_employees(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            target_file = temp_path / "target_employees.json"
            results_file = temp_path / "migration_results.json"
            review_file = temp_path / "migration_review.json"
            target_data = {
                "employees": [
                    {"employee_id": 402, "name": "Omar Hassan"},
                    {"employee_id": 500, "name": "Aarav Sharma"},
                    {"employee_id": 502, "name": "Rahul Verma"},
                ]
            }
            expected_target_data = {
                "employees": [
                    {"employee_id": 500, "name": "Aarav Sharma"},
                    {"employee_id": 502, "name": "Rahul Verma"},
                ]
            }
            target_file.write_text(json.dumps(target_data), encoding="utf-8")
            results_file.write_text("{}", encoding="utf-8")
            review_file.write_text("{}", encoding="utf-8")

            with patch.object(main, "TARGET_FILE", target_file), \
                 patch.object(main, "RESULTS_FILE", results_file), \
                 patch.object(main, "REVIEW_FILE", review_file):
                import asyncio
                asyncio.run(main.reset_results())

            self.assertEqual(json.loads(target_file.read_text(encoding="utf-8")), expected_target_data)

    def test_create_target_employee_rejects_existing_employee_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_file = Path(temp_dir) / "target_employees.json"
            target_file.write_text(
                json.dumps({"employees": [{"employee_id": 402, "name": "Omar Hassan"}]}),
                encoding="utf-8"
            )

            with patch.object(main, "TARGET_FILE", target_file):
                import asyncio
                with self.assertRaises(main.HTTPException) as context:
                    asyncio.run(main.create_target_employee({"employee_id": 402, "name": "Another Omar"}))

            self.assertEqual(context.exception.status_code, 409)
            self.assertEqual(len(json.loads(target_file.read_text(encoding="utf-8"))["employees"]), 1)

    def test_delete_target_employee_removes_only_requested_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_file = Path(temp_dir) / "target_employees.json"
            target_file.write_text(
                json.dumps({
                    "employees": [
                        {"employee_id": 500, "name": "Aarav Sharma"},
                        {"employee_id": 502, "name": "Rahul Verma"},
                    ]
                }),
                encoding="utf-8"
            )

            with patch.object(main, "TARGET_FILE", target_file):
                import asyncio
                response = asyncio.run(main.delete_target_employee("500"))

            self.assertEqual(response["status"], "success")
            remaining = json.loads(target_file.read_text(encoding="utf-8"))["employees"]
            self.assertEqual([employee["employee_id"] for employee in remaining], [502])


if __name__ == "__main__":
    unittest.main()

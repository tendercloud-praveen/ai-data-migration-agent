 # AI Data Migration Agent

An AI-assisted employee data migration tool. It accepts CSV/XLSX exports, maps source columns to the target employee schema with LangGraph and Groq, validates and scores every record, asks a human to resolve uncertain records, and stores approved records in the mock target system.

## Project Structure

```text
data-migration-agent/
├── backend/
│   └── app/
│       ├── main.py
│       └── agent/
│           ├── mapping_agent.py
│           ├── validation_agent.py
│           └── confidence_agent.py
├── frontend/
│   └── app.py
├── data/
│   ├── uploads/
│   └── results/
│       ├── migration_results.json
│       ├── migration_review.json
│       └── target_employees.json
└── requirements.txt
```

## Workflow

```text
Upload CSV/XLSX files
	↓
AI column mapping
	↓
Cleaning and normalization
	↓
Validation
	↓
Confidence scoring
	↓
100% confidence ───────────────→ Save to target system
	↓
Human Review
	↓
Edit and Retry
	↓
100% confidence ───────────────→ Save to target system
```

Records below 100% confidence are not migrated. They remain in Human Review until the user corrects them and Retry validates them successfully.

When multiple uploaded files contain the same employee ID, the backend reconciles complementary fields conservatively. A blank field can be filled from another matching source row only when the available nonblank values agree. Conflicting values are never chosen automatically; the record remains available for Human Review.

## Human Review

Human Review is used for:

- Missing employee name
- Missing or invalid email
- Missing or invalid joining date
- Missing department
- Duplicate employee IDs
- Employee IDs that already exist in the target system

Duplicate records are grouped by `employee_id` and shown side by side. The user chooses which `record_id` to keep. The rejected source row is removed only from the migration dataset; the original CSV/XLSX file is never changed.

Retry always runs validation and confidence scoring again. A successful Retry shows 100% confidence and automatically stores the record in the target system.

## Approval Rules

System-approved record:

```json
{
    "confidence_score": 100,
    "confidence_status": "SYSTEM_APPROVED",
    "approval_source": "SYSTEM"
}
```

Human-corrected record after successful Retry:

```json
{
    "confidence_score": 100,
    "confidence_status": "SYSTEM_APPROVED",
    "approval_source": "HUMAN",
    "human_review_status": "RESOLVED"
}
```

The record must still pass validation after human editing. The UI never marks a record approved without revalidation.

## Target System

The mock target system is stored in:

```text
data/results/target_employees.json
```

Target employee objects contain only employee data:

```json
{
    "employees": [
	{
	    "employee_id": "101",
	    "name": "Rahul Sharma",
	    "email": "rahul@example.com",
	    "joining_date": "15/01/2024",
	    "department": "Engineering",
	    "phone": "",
	    "salary": "",
	    "location": ""
	}
    ]
}
```

The target uses `employee_id` as its unique key. Existing target employees are never overwritten. A conflicting uploaded record is sent to Human Review instead.

Records that reach 100% confidence are migrated automatically. The UI reports the target status as `MIGRATED` or `FAILED`.

## Result Files

### `migration_results.json`

The approved migration audit. It contains records that reached 100% confidence and their target migration status.

### `migration_review.json`

The internal review state. It contains records still needing Human Review, duplicate decisions, retry attempts, validation issues, and escalation state.

### `target_employees.json`

The mock target system. It contains only clean employee objects, not validation or debug fields.

## Refresh Behavior

Starting a new Streamlit session clears the current run data:

- `migration_results.json` is removed.
- `migration_review.json` is removed.
- `target_employees.json` is reset to `{ "employees": [] }`.

Uploaded source files are not modified.

## Technology

- Python 3.11+
- FastAPI
- Uvicorn
- Streamlit
- Pandas
- OpenPyXL
- LangGraph
- Groq AI through LangChain

## Configuration

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key
```

Do not commit `.env`, API keys, or private source data.

## Installation

From the project root:

```powershell
pip install -r requirements.txt
```

## Tests

Run the backend workflow tests from the project root:

```powershell
python -m unittest discover -s backend\tests -v
```

The tests cover conservative multi-file reconciliation, duplicate grouping, target employee conflicts, and escalation after repeated failed Retry attempts.

## Run the Application

Open two terminals.

### Backend

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

### Frontend

```powershell
cd frontend
python -m streamlit run app.py
```

The Streamlit UI runs at `http://localhost:8501`.

## UI Workspaces

- **Upload Files**: upload source files and start the agent.
- **Dashboard**: see processed, approved, review, and migrated counts.
- **Human Review**: resolve duplicates and edit invalid records.
- **Audit**: inspect confidence, approval source, target status, errors, and escalation state.

## Safety and Audit Rules

- Source CSV/XLSX files are never overwritten.
- Records below 100% confidence cannot migrate.
- Existing target employee IDs are not overwritten.
- Every record has a stable `record_id`, such as `employee_details.csv:2`.
- Duplicate decisions are made by a human.
- Validation runs again after every edit and Retry.
- Errors and escalations remain visible in the Audit workspace.

## Autonomy Boundary

The agent acts without human confirmation when the mapping is usable, required fields validate, confidence reaches 100%, and the employee ID does not already exist in the target system. It escalates when duplicate rows conflict, required data is invalid, a target ID already exists, or repeated Retry attempts do not resolve the issue. This keeps routine migration autonomous while preventing silent data loss or target overwrites.

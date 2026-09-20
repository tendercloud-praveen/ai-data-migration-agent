import json
from typing import Any, Dict, List

import requests
import streamlit as st


API_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Migration Control Room",
    page_icon="M",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
    :root { --ink:#17252b; --muted:#66777c; --paper:#f4f7f5; --panel:#fff; --line:#dce7e1; --teal:#176b68; --deep:#173f42; --mint:#dff3e8; --amber:#fff1d2; --red:#fff0ec; }
    html, body, [class*="css"] { font-family:'DM Sans',sans-serif; color:var(--ink); }
    .stApp { background:var(--paper); }
    [data-testid="stSidebar"] { background:var(--deep); border:0; }
    [data-testid="stSidebar"] * { color:#effaf4; }
    [data-testid="stSidebar"] .stRadio label { color:#effaf4; }
    h1,h2,h3 { font-family:'Space Grotesk',sans-serif; letter-spacing:0; }
    h1 { font-size:2.6rem !important; line-height:1.05 !important; }
    h2 { font-size:1.55rem !important; }
    h3 { font-size:1.08rem !important; }
    .eyebrow { color:var(--teal); font-size:.72rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
    .muted { color:var(--muted); }
    .brand { font-family:'Space Grotesk',sans-serif; font-size:1.3rem; font-weight:700; }
    .brand-sub { color:#a9d6c5; font-size:.78rem; margin:3px 0 25px; }
    .shell-card { background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:22px; box-shadow:0 8px 26px rgba(23,63,66,.05); animation:enter .35s ease both; }
    .upload-card { background:linear-gradient(135deg,#fff 0%,#edf8f1 100%); border:1px solid #c8e5d7; border-radius:18px; padding:30px; margin:20px 0; }
    .state { border-radius:10px; padding:12px 14px; border:1px solid var(--line); background:#fbfdfc; margin:7px 0; }
    .state.good { background:var(--mint); border-color:#b7dfcb; }
    .state.review { background:var(--amber); border-color:#efd39b; }
    .state.blocked { background:var(--red); border-color:#efc6bd; }
    .record-id { color:var(--muted); font-size:.78rem; font-weight:600; }
    .stButton button { border-radius:9px; font-weight:600; transition:transform .15s ease,box-shadow .15s ease; }
    .stButton button:hover { transform:translateY(-1px); box-shadow:0 6px 14px rgba(23,107,104,.16); }
    [data-testid="stMetric"] { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px; animation:enter .4s ease both; }
    [data-testid="stMetricValue"] { color:var(--teal); }
    [data-testid="stExpander"] { border:1px solid var(--line); border-radius:12px; background:#fff; }
    @keyframes enter { from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:translateY(0); } }
    </style>
    """,
    unsafe_allow_html=True
)


def api_request(method: str, path: str, **kwargs):
    kwargs.setdefault("timeout", 120)
    return requests.request(method, f"{API_URL}{path}", **kwargs)


def empty_results() -> Dict[str, Any]:
    return {"status": "success", "message": "No analysis yet", "files": []}


def make_upload(files):
    return [("files", (file.name, file.getvalue(), file.type)) for file in files]


def all_records(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = []
    for file_data in data.get("files", []):
        records.extend(file_data.get("records", []))
    return records


def counts(data: Dict[str, Any]):
    records = [record for record in all_records(data) if record.get("duplicate_status") != "REMOVED"]
    approved = sum(record.get("confidence_status") == "SYSTEM_APPROVED" for record in records)
    review = len(records) - approved
    migrated = sum(record.get("migration_status") == "MIGRATED" for record in records)
    return approved, review, migrated, len(records)


def set_record(data, record_id, updated_record):
    for file_data in data.get("files", []):
        for index, record in enumerate(file_data.get("records", [])):
            if record.get("record_id") == record_id:
                file_data["records"][index] = updated_record
                return


def render_sidebar(active_view: str):
    st.sidebar.markdown('<div class="brand">Migrate / AI</div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="brand-sub">Client migration control room</div>', unsafe_allow_html=True)
    st.sidebar.markdown("### Workspace")
    return st.sidebar.radio(
        "Navigation",
        ["Upload Files", "Dashboard", "Human Review", "Audit"],
        index=["Upload Files", "Dashboard", "Human Review", "Audit"].index(active_view),
        label_visibility="collapsed",
        key="workspace_navigation"
    )


def render_topbar(active_view: str):
    st.markdown(f'<div class="eyebrow">Migration control room / {active_view}</div>', unsafe_allow_html=True)
    st.title(active_view)


def render_upload():
    if st.session_state.pop("analysis_complete_notice", False):
        st.markdown(
            '<div class="state good"><strong>Analysis completed successfully</strong><br>'
            'Your files were mapped, cleaned, validated, and scored. Open the Dashboard to see the results.</div>',
            unsafe_allow_html=True
        )
        if st.button("Go to Dashboard", type="primary"):
            st.session_state["active_view"] = "Dashboard"
            st.rerun()

    st.markdown(
        '<div class="upload-card"><div class="eyebrow">Step 01 / Ingest</div>'
        '<h2>Bring in source records</h2>'
        '<p class="muted">Upload one or more CSV or Excel exports. The agent will map, clean, validate, and score them before anything reaches the target system.</p></div>',
        unsafe_allow_html=True
    )
    uploaded_files = st.file_uploader(
        "Source files",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
        help="Source files are preserved and never modified."
    )
    if not uploaded_files:
        st.info("Choose source files to begin the migration run.")
        return
    st.caption(f"{len(uploaded_files)} file(s) ready for analysis")
    if not st.button("Start AI analysis", type="primary"):
        return
    files = make_upload(uploaded_files)
    try:
        with st.status("Running migration agents", expanded=True) as status:
            st.write("Uploading source files")
            upload_response = api_request("POST", "/upload", files=files, timeout=60)
            upload_response.raise_for_status()
            st.write("Mapping source fields with AI")
            mapping_response = api_request("POST", "/analyze-mapping", files=files)
            mapping_response.raise_for_status()
            st.write("Cleaning, validating, and scoring records")
            validation_response = api_request("POST", "/validate-data", files=files)
            validation_response.raise_for_status()
            status.update(label="Analysis complete", state="complete", expanded=False)
        st.session_state["upload_data"] = upload_response.json()
        st.session_state["mapping_data"] = mapping_response.json()
        st.session_state["validation_data"] = validation_response.json()
        st.session_state["analysis_complete_notice"] = True
        st.rerun()
    except requests.RequestException as error:
        st.error(f"The migration service could not complete the run: {error}")


def render_target_employees():
    try:
        response = api_request("GET", "/target/employees", timeout=15)
        response.raise_for_status()
        employees = response.json().get("employees", [])
    except requests.RequestException:
        st.warning("Target system is unavailable.")
        return
    if not employees:
        st.info("Target system is currently empty.")
        return
    for employee in employees:
        employee_id = employee.get("employee_id", "")
        left, right = st.columns([8, 1])
        with left:
            st.markdown(
                f'<div class="state"><strong>ID {employee_id}</strong> &nbsp; {employee.get("name", "")} &nbsp; <span class="muted">{employee.get("department", "")}</span></div>',
                unsafe_allow_html=True
            )
        with right:
            if st.button("X", key=f"delete_target_{employee_id}", help=f"Delete target employee {employee_id}"):
                try:
                    delete_response = api_request("DELETE", f"/target/employees/{employee_id}", timeout=15)
                    if delete_response.status_code == 200:
                        st.success(f"Target ID {employee_id} deleted.")
                        st.rerun()
                    st.error(delete_response.text)
                except requests.RequestException as error:
                    st.error(f"Delete failed: {error}")


def render_dashboard(data: Dict[str, Any]):
    approved, review, migrated, total = counts(data)
    st.markdown('<p class="muted">A live view of the agent run and its escalation boundary.</p>', unsafe_allow_html=True)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Records processed", total)
    metric_columns[1].metric("System approved", approved)
    metric_columns[2].metric("Human review", review)
    metric_columns[3].metric("Migrated", migrated)
    st.subheader("Run status")
    steps = [
        ("01", "Source ingestion", "Files received"),
        ("02", "AI field mapping", "Mapping proposed"),
        ("03", "Validation and confidence", "Records scored"),
        ("04", "Human supervision", "Escalations resolved" if review == 0 else f"{review} item(s) need attention"),
        ("05", "Target migration", "Ready to push" if approved else "Waiting for approval")
    ]
    for number, title, detail in steps:
        state_class = "good" if number != "04" or review == 0 else "review"
        st.markdown(f'<div class="state {state_class}"><strong>{number} &nbsp; {title}</strong><br><span class="muted">{detail}</span></div>', unsafe_allow_html=True)
    st.subheader("Approved records")
    if approved:
        st.markdown(
            f'<div class="state good"><strong>{approved} record(s) approved and migrated</strong><br>'
            'All displayed approved records reached 100% confidence and were saved to the target system.</div>',
            unsafe_allow_html=True
        )
    else:
        st.info("No records have reached 100% confidence yet.")

    if st.button("View migrated records", type="primary"):
        st.session_state["show_migrated_records"] = not st.session_state.get(
            "show_migrated_records",
            False
        )
        st.rerun()

    if st.session_state.get("show_migrated_records", False):
        st.subheader("Target system records")
        st.caption("These records are currently stored in target_employees.json.")
        render_target_employees()

    if approved:
        st.success("Approved records are migrated automatically to the target system.")


def resolve_duplicate(data, record_id):
    try:
        response = api_request("POST", "/resolve-duplicate", json={"keep_record_id": record_id})
        response.raise_for_status()
        payload = response.json()
        set_record(data, payload["kept_record_id"], payload["record"])
        for removed_id in payload.get("removed_record_ids", []):
            for record in all_records(data):
                if record.get("record_id") == removed_id:
                    record["duplicate_status"] = "REMOVED"
        st.session_state["validation_data"] = data
        st.success(f"{record_id} kept. Retry is required before approval.")
        st.rerun()
        
    except requests.RequestException as error:
        st.error(f"Duplicate resolution failed: {error}")


def retry_record(data, record, edited_values=None):
    payload = dict(record)
    if edited_values:
        payload.update(edited_values)
    try:
        response = api_request("POST", "/retry-record", json=payload)
        response.raise_for_status()
        updated_record = response.json()["record"]
        retry_response_data = response.json()
        record_id = record.get("record_id")
        set_record(data, record_id, updated_record)
        if (
            updated_record.get("confidence_score") == 100
            and updated_record.get("confidence_status") == "SYSTEM_APPROVED"
        ):
            st.session_state.setdefault("retry_completed_ids", set()).add(record_id)
        else:
            st.session_state.setdefault("retry_completed_ids", set()).discard(record_id)
        st.session_state["last_retry_result"] = {
            "record_id": record_id,
            "score": updated_record.get("confidence_score", 0),
            "status": updated_record.get("confidence_status", "HUMAN_REVIEW"),
            "saved": retry_response_data.get("saved_to_migration_results", False)
        }
        st.session_state["validation_data"] = data
        st.rerun()
    except requests.HTTPError as error:
        detail = error.response.text if error.response is not None else str(error)
        st.error(f"Retry could not be completed: {detail}")
    except requests.RequestException as error:
        st.error(f"Retry connection failed: {error}")


def render_duplicate_review(data: Dict[str, Any]):
    groups = {}
    for record in all_records(data):
        group_id = record.get("duplicate_group_id")
        if (
            group_id
            and record.get("duplicate_status") != "REMOVED"
            and not (
                record.get("duplicate_status") == "KEPT"
                and record.get("confidence_status") == "SYSTEM_APPROVED"
            )
        ):
            groups.setdefault(group_id, []).append(record)
    for group_id, records in groups.items():
        employee_id = records[0].get("employee_id", "")
        st.markdown(f"### Duplicate employee ID: {employee_id}")
        st.caption("Choose the record that should remain. The other source row is removed from migration, not from the source file.")
        columns = st.columns(len(records))
        for column, record in zip(columns, records):
            with column:
                st.markdown('<div class="shell-card">', unsafe_allow_html=True)
                st.markdown(f'<div class="record-id">{record.get("record_id", "")}</div>', unsafe_allow_html=True)
                for field in ["employee_id", "name", "email", "joining_date", "department"]:
                    st.write(f"**{field.replace('_', ' ').title()}**  {record.get(field, '')}")
                if record.get("duplicate_retry_required"):
                    retry_completed = record.get("record_id") in st.session_state.get("retry_completed_ids", set())
                    if st.button(
                        "Retry completed" if retry_completed else "Retry",
                        key=f"retry_duplicate_{record.get('record_id')}",
                        type="primary",
                        disabled=retry_completed
                    ):
                        retry_record(data, record)
                elif st.button(f"Keep {record.get('record_id')}", key=f"keep_{group_id}_{record.get('record_id')}", type="primary"):
                    resolve_duplicate(data, record.get("record_id"))
                st.markdown('</div>', unsafe_allow_html=True)


def render_human_review(data: Dict[str, Any]):
    last_retry = st.session_state.pop("last_retry_result", None)
    if last_retry:
        if last_retry["status"] == "SYSTEM_APPROVED" and last_retry["score"] == 100:
            st.markdown(
                f'<div class="state good"><strong>Retry completed: {last_retry["record_id"]}</strong><br>'
                '<strong>Confidence: 100%</strong> · System Approved · '
                '<strong>Saved to target_employees.json</strong> · Target status: MIGRATED.</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="state review"><strong>Retry completed: {last_retry["record_id"]}</strong><br>'
                f'Confidence: <strong>{last_retry["score"]}%</strong>. The record still requires Human Review.</div>',
                unsafe_allow_html=True
            )

    records = [record for record in all_records(data) if record.get("confidence_status") != "SYSTEM_APPROVED" and record.get("duplicate_status") != "REMOVED"]
    if not records:
        st.markdown('<div class="state good"><strong>Queue clear</strong><br>No escalations need human attention.</div>', unsafe_allow_html=True)
        return
    st.markdown(f'<div class="state review"><strong>{len(records)} escalation(s) need a decision</strong><br>Review the evidence, correct only what is necessary, then Retry.</div>', unsafe_allow_html=True)
    render_duplicate_review(data)
    for index, record in enumerate(records):
        if record.get("duplicate_group_id"):
            continue
        record_id = record.get("record_id", f"record-{index}")
        with st.expander(f"{record_id}  |  {record.get('confidence_score', 0)}% confidence", expanded=True):
            issues = record.get("validation_issues", [])
            st.markdown(f'<div class="state blocked"><strong>Reason for escalation</strong><br>{"<br>".join(issues) or "Target conflict"}</div>', unsafe_allow_html=True)
            st.write(f"Employee ID: {record.get('employee_id', '')} | Name: {record.get('name', '')} | Email: {record.get('email', '')}")
            if st.button("Edit", key=f"edit_{record_id}", type="primary"):
                st.session_state[f"editing_{record_id}"] = True
            if st.session_state.get(f"editing_{record_id}", False):
                render_edit_form(data, record, record_id)


def render_edit_form(data: Dict[str, Any], record: Dict[str, Any], form_key: str):
    record_id = record.get("record_id", form_key)
    st.caption("Correct the fields, then Retry validation. The record remains Human Review until it passes again.")
    with st.form(f"edit_form_{form_key}"):
        values = {}
        fields = ["employee_id", "name", "email", "joining_date", "department", "phone", "salary", "location"]
        edit_columns = st.columns(2)
        for field_index, field in enumerate(fields):
            with edit_columns[field_index % 2]:
                values[field] = st.text_input(
                    field.replace("_", " ").title(),
                    value=str(record.get(field, "")),
                    key=f"{form_key}_{field}"
                )
        submitted = st.form_submit_button("Retry validation", type="primary")
    if submitted:
        retry_record(data, record, values)


def render_audit(data: Dict[str, Any]):
    records = all_records(data)
    if not records:
        st.info("No audit records yet. Run an analysis first.")
        return
    rows = []
    for record in records:
        if record.get("duplicate_status") == "REMOVED":
            continue
        rows.append({
            "Record": record.get("record_id", ""),
            "Employee ID": record.get("employee_id", ""),
            "Confidence": f"{record.get('confidence_score', 0)}%",
            "Decision": record.get("confidence_status", "HUMAN_REVIEW"),
            "Approved by": record.get("approval_source", "HUMAN_REVIEW"),
            "Target system": record.get("migration_status", "PENDING"),
            "Error": record.get("migration_error") or "",
            "Escalation": record.get("escalation_status", "")
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.download_button("Download audit JSON", data=json.dumps(data, indent=2, default=str), file_name="migration_audit.json", mime="application/json")


if "session_initialized" not in st.session_state:
    try:
        response = api_request("POST", "/reset-results", timeout=15)
        if response.status_code == 200:
            st.session_state["session_initialized"] = True
    except requests.RequestException:
        st.session_state["session_initialized"] = True

if "validation_data" not in st.session_state:
    st.session_state["validation_data"] = empty_results()

active_view = render_sidebar(st.session_state.get("active_view", "Upload Files"))
st.session_state["active_view"] = active_view
render_topbar(active_view)
data = st.session_state["validation_data"]

if active_view == "Upload Files":
    render_upload()
elif active_view == "Dashboard":
    render_dashboard(data)
elif active_view == "Human Review":
    render_human_review(data)
else:
    render_audit(data)

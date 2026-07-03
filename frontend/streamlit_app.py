from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:5000/api/v1")


def main() -> None:
    st.set_page_config(page_title="BaoHiem Legal AI Admin", layout="wide")
    st.title("Admin Console")

    if "access_token" not in st.session_state:
        st.session_state.access_token = ""
    if "current_user" not in st.session_state:
        st.session_state.current_user = None

    if not st.session_state.access_token:
        render_login()
        return

    render_sidebar()
    page = st.sidebar.radio(
        "View",
        ["DOCX Import", "Documents", "Pipeline"],
        label_visibility="collapsed",
    )
    if page == "DOCX Import":
        render_import()
    elif page == "Documents":
        render_documents()
    else:
        render_pipeline()


def render_login() -> None:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        response = requests.post(
            f"{API_BASE_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=30,
        )
        if not response.ok:
            show_error(response)
            return
        payload = response.json()
        st.session_state.access_token = payload["access_token"]
        st.session_state.current_user = payload["user"]
        st.rerun()


def render_sidebar() -> None:
    user = st.session_state.current_user or {}
    st.sidebar.caption(f"Signed in as {user.get('username', 'unknown')}")
    if st.sidebar.button("Logout"):
        requests.post(
            f"{API_BASE_URL}/auth/logout",
            headers=auth_headers(),
            timeout=30,
        )
        st.session_state.access_token = ""
        st.session_state.current_user = None
        st.rerun()


def render_import() -> None:
    st.subheader("Import Legal DOCX")
    with st.form("docx_import_form"):
        uploaded_file = st.file_uploader("DOCX file", type=["docx"])
        document_number = st.text_input("Document number override")
        title = st.text_input("Title override")
        source_url = st.text_input("Source URL")
        issued_date = st.text_input(
            "Issued date",
            help="Use ISO date format: YYYY-MM-DD, for example 2026-07-03.",
        )
        st.caption("Issued date format: YYYY-MM-DD, for example 2026-07-03.")
        effective_date = st.text_input(
            "Effective date",
            help="Use ISO date format: YYYY-MM-DD, for example 2026-07-03.",
        )
        st.caption("Effective date format: YYYY-MM-DD, for example 2026-07-03.")
        expiry_date = st.text_input(
            "Expiry date",
            help="Use ISO date format: YYYY-MM-DD, for example 2026-07-03.",
        )
        st.caption("Expiry date format: YYYY-MM-DD, for example 2026-07-03.")
        validity_status = st.selectbox(
            "Validity status",
            ["unknown", "active", "expired", "replaced", "abolished", "suspended"],
        )
        relations_json = st.text_area("Relations JSON", height=120)
        submitted = st.form_submit_button("Import", type="primary")

    if not submitted:
        return
    if uploaded_file is None:
        st.error("DOCX file is required.")
        return

    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    data = {
        "document_number": document_number,
        "title": title,
        "source_url": source_url,
        "issued_date": issued_date,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "validity_status": validity_status,
        "relations_json": relations_json,
    }
    response = requests.post(
        f"{API_BASE_URL}/admin/documents/import",
        headers=auth_headers(),
        data=data,
        files=files,
        timeout=120,
    )
    if not response.ok:
        show_error(response)
        return
    st.success("Import reached ready_for_review.")
    st.json(response.json())


def render_documents() -> None:
    st.subheader("Documents")
    response = requests.get(
        f"{API_BASE_URL}/admin/documents",
        headers=auth_headers(),
        timeout=30,
    )
    if not response.ok:
        show_error(response)
        return

    documents = response.json().get("documents", [])
    if not documents:
        st.info("No documents imported yet.")
        return

    options = {
        f"{doc.get('document_number')} - {doc.get('title')}": doc["document_id"]
        for doc in documents
    }
    selected = st.selectbox("Document", list(options.keys()))
    if selected:
        render_document_detail(options[selected])


def render_document_detail(document_id: str) -> None:
    response = requests.get(
        f"{API_BASE_URL}/admin/documents/{document_id}",
        headers=auth_headers(),
        timeout=30,
    )
    if not response.ok:
        show_error(response)
        return
    detail = response.json()
    document = detail.get("document", {})
    version = detail.get("version", {})
    version_status = version.get("status")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Metadata")
        st.json(document)
    with right:
        st.markdown("#### Current Review Version")
        st.json(version)

    render_publish_warnings(document, version, detail)

    st.markdown("#### Relations")
    relations = detail.get("relations", [])
    if relations:
        st.dataframe(relations, use_container_width=True)
    else:
        st.info("No admin-curated relations provided.")

    st.markdown("#### Chunk Preview")
    for chunk in detail.get("chunks_preview", []):
        with st.expander(chunk.get("citation_label") or chunk.get("chunk_id")):
            st.caption(chunk.get("chunk_level"))
            st.write(chunk.get("content"))

    st.markdown("#### Pipeline Events")
    events = detail.get("pipeline_events", [])
    if events:
        st.dataframe(events, use_container_width=True)
    else:
        st.info("No pipeline events found for this document version.")

    can_publish = version_status == "ready_for_review"
    if st.button("Publish", type="primary", disabled=not can_publish):
        with st.spinner("Publishing and indexing..."):
            publish_response = requests.post(
                f"{API_BASE_URL}/admin/documents/{document_id}/publish",
                headers=auth_headers(),
                timeout=600,
            )
        if not publish_response.ok:
            show_error(publish_response)
            return
        st.success("Published successfully!")
        st.json(publish_response.json())
        st.rerun()
    if version_status == "published":
        st.success("Published successfully!")
    elif not can_publish:
        st.caption("Publish is available only for ready_for_review documents.")


def render_pipeline() -> None:
    st.subheader("Pipeline Runs")
    response = requests.get(
        f"{API_BASE_URL}/admin/pipeline",
        headers=auth_headers(),
        timeout=30,
    )
    if not response.ok:
        show_error(response)
        return
    runs = response.json().get("pipeline_runs", [])
    if not runs:
        st.info("No pipeline runs yet.")
        return
    st.dataframe(runs, use_container_width=True)

    run_id = st.text_input("Pipeline run id")
    if st.button("Load run") and run_id:
        detail_response = requests.get(
            f"{API_BASE_URL}/admin/pipeline/{run_id}",
            headers=auth_headers(),
            timeout=30,
        )
        if not detail_response.ok:
            show_error(detail_response)
            return
        st.json(detail_response.json())
    if st.button("Rollback run", disabled=not bool(run_id)):
        rollback_response = requests.post(
            f"{API_BASE_URL}/admin/pipeline/{run_id}/rollback",
            headers=auth_headers(),
            timeout=180,
        )
        if not rollback_response.ok:
            show_error(rollback_response)
            return
        st.success("Rollback completed.")
        st.json(rollback_response.json())


def render_publish_warnings(
    document: dict[str, Any],
    version: dict[str, Any],
    detail: dict[str, Any],
) -> None:
    warnings = []
    if document.get("validity_status") == "unknown":
        warnings.append(
            "validity_status is unknown; default active-only retrieval may exclude this document."
        )
    if not document.get("effective_date"):
        warnings.append("effective_date is missing.")
    if not detail.get("relations"):
        warnings.append("No admin-curated relations are available.")
    metadata = parse_json(version.get("metadata_json"))
    warnings.extend(metadata.get("warnings") or [])
    for warning in dict.fromkeys(warnings):
        st.warning(warning)


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {st.session_state.access_token}"}


def show_error(response: requests.Response) -> None:
    try:
        payload: Any = response.json()
    except json.JSONDecodeError:
        payload = response.text
    st.error(f"Request failed: {response.status_code}")
    st.json(payload)


def parse_json(raw_value: Any) -> dict[str, Any]:
    if not raw_value:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    try:
        parsed = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


if __name__ == "__main__":
    main()

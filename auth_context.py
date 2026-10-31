import hmac
import secrets
from typing import Optional

import streamlit as st


def create_auth_context(student_id: str) -> str:
    """Create a random authentication token for the logged-in session."""
    if not student_id or not student_id.strip():
        raise ValueError("A valid student ID is required.")

    token = secrets.token_urlsafe(32)

    st.session_state["_auth_context_token"] = token
    st.session_state["_auth_context_student_id"] = student_id.strip().upper()

    return token


def get_authenticated_student_id(token: str) -> Optional[str]:
    """Verify a token against the current Streamlit session."""
    if not token:
        return None

    stored_token = st.session_state.get("_auth_context_token")
    stored_student_id = st.session_state.get("_auth_context_student_id")

    if not stored_token or not stored_student_id:
        return None

    if not hmac.compare_digest(token, stored_token):
        return None

    return stored_student_id


def clear_auth_context() -> None:
    """Clear the authentication context when the user logs out."""
    st.session_state.pop("_auth_context_token", None)
    st.session_state.pop("_auth_context_student_id", None)
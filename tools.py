import csv
from pathlib import Path

from auth_context import get_authenticated_student_id

from database import (
    save_support_request,
    get_student_requests,
)

BASE_DIR = Path(__file__).resolve().parent
STUDENT_FILE = BASE_DIR / "data" / "students.csv"


def _normalize_student_id(student_id: str) -> str:
    """Normalize a student ID for comparison."""
    return (student_id or "").strip().upper()


def _verify_authenticated_student(auth_token: str):
    """
    Verify the authentication token against the current
    authenticated Streamlit session.

    Returns the verified student ID, or None if verification fails.
    """
    if not auth_token:
        return None

    try:
        verified_student_id = get_authenticated_student_id(auth_token)
    except Exception:
        # Fail closed if authentication context cannot be verified.
        return None

    if not verified_student_id:
        return None

    return _normalize_student_id(verified_student_id)


def _check_student_access(
    requested_student_id: str,
    auth_token: str,
):
    """
    Verify the session identity and confirm that the requested
    student ID belongs to that authenticated session.
    """
    verified_student_id = _verify_authenticated_student(auth_token)

    if not verified_student_id:
        return None

    requested_id = _normalize_student_id(requested_student_id)

    if not requested_id or requested_id != verified_student_id:
        return None

    return verified_student_id


def get_student_record(
    student_id: str,
    auth_token: str,
) -> dict:
    """Retrieve a student record for the authenticated student only."""

    verified_student_id = _check_student_access(
        student_id,
        auth_token,
    )

    if not verified_student_id:
        return {
            "success": False,
            "message": (
                "Access denied. Please sign in again and access "
                "only the student details associated with your account."
            ),
        }

    if not STUDENT_FILE.exists():
        return {
            "success": False,
            "message": "Student data file is unavailable.",
        }

    try:
        with STUDENT_FILE.open(
            mode="r",
            newline="",
            encoding="utf-8",
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                row_student_id = _normalize_student_id(
                    row.get("student_id", "")
                )

                if row_student_id == verified_student_id:
                    return {
                        "success": True,
                        "student": row,
                    }

    except (OSError, csv.Error):
        return {
            "success": False,
            "message": "Unable to read student data at this time.",
        }

    return {
        "success": False,
        "message": "No matching student record was found.",
    }


def create_support_request(
    student_id: str,
    category: str,
    description: str,
    auth_token: str,
) -> dict:
    """Create a support request for the authenticated student only."""

    verified_student_id = _check_student_access(
        student_id,
        auth_token,
    )

    if not verified_student_id:
        return {
            "success": False,
            "message": (
                "Access denied. Please sign in again before "
                "submitting a support request."
            ),
        }

    if not isinstance(category, str) or not category.strip():
        return {
            "success": False,
            "message": "Please provide an issue category.",
        }

    if not isinstance(description, str) or not description.strip():
        return {
            "success": False,
            "message": "Please describe the issue.",
        }

    result = save_support_request(
        verified_student_id,
        category.strip(),
        description.strip(),
    )

    if not result.get("success"):
        return result

    return {
        "success": True,
        "request_id": result["request_id"],
        "message": (
            "Your support request has been submitted successfully! "
            f"Your request ID is {result['request_id']}. "
            "Current status: Open."
        ),
    }


def get_student_requests_for_user(
    student_id: str,
    auth_token: str,
) -> dict:
    """Retrieve support requests for the authenticated student only."""

    verified_student_id = _check_student_access(
        student_id,
        auth_token,
    )

    if not verified_student_id:
        return {
            "success": False,
            "message": (
                "Access denied. Please sign in again before "
                "viewing support request history."
            ),
        }

    requests = get_student_requests(verified_student_id)

    return {
        "success": True,
        "requests": requests,
    }
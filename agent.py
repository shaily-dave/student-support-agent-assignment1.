import re
import streamlit as st

from auth_context import get_authenticated_student_id
from tools import (
    get_student_record,
    create_support_request,
    get_student_requests_for_user,
)
from memory import (
    save_message,
    get_conversation_history,
    sanitize_message,
)
from retrieval import search_policy
from database import log_audit_event


# ============================================================
# 1. RESPONSE HELPER
# ============================================================

def make_response(
    student_id,
    answer,
    success=True,
    tool_used=None,
    **extra
):
    """Create a response and save it to conversation memory."""

    try:
        answer = sanitize_message(answer)
    except Exception:
        answer = str(answer)

    try:
        save_message(student_id, "assistant", answer)
    except Exception:
        pass

    return {
        "success": success,
        "answer": answer,
        "tool_used": tool_used,
        **extra,
    }


# ============================================================
# 2. AUDIT LOGGING
# ============================================================

def record_security_event(
    student_id,
    action,
    resource,
    outcome,
    details
):
    """Record an event in the audit log."""

    try:
        log_audit_event(
            actor_student_id=student_id,
            action=action,
            resource=resource,
            outcome=outcome,
            details=details,
        )
    except Exception:
        pass


# ============================================================
# 3. AUTHENTICATION
# ============================================================

def verify_student(student_id, auth_token):
    """Verify that the student ID matches the authenticated session."""

    try:
        authenticated_id = get_authenticated_student_id(auth_token)
    except Exception:
        authenticated_id = None

    if not authenticated_id:
        return None

    authenticated_id = authenticated_id.strip().upper()

    if not student_id or (
        student_id.strip().upper() != authenticated_id
    ):
        record_security_event(
            student_id=authenticated_id,
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            resource="student_records",
            outcome="DENIED",
            details="Student ID did not match authenticated session.",
        )
        return None

    return authenticated_id


# ============================================================
# 4. STUDENT RECORD
# ============================================================

def fetch_student_record(student_id, auth_token):
    """Fetch and verify the current student's record."""

    result = get_student_record(
        student_id=student_id,
        auth_token=auth_token,
    )

    if not result.get("success"):
        return None, result.get(
            "message",
            "Unable to retrieve your student record."
        )

    student = result.get("student", {})

    record_id = str(
        student.get("student_id", "")
    ).strip().upper()

    if record_id != student_id:
        record_security_event(
            student_id=student_id,
            action="STUDENT_RECORD_VERIFICATION_FAILED",
            resource="student_records",
            outcome="DENIED",
            details="Returned record did not match authenticated student.",
        )

        return None, (
            "Access denied. Your student record could not be verified."
        )

    return student, None


# ============================================================
# 5. SUPPORT REQUEST DRAFT
# ============================================================

def prepare_support_request(student_id, category, description):
    """Save a draft in the current session without submitting it."""

    category = sanitize_message(category).strip()
    description = sanitize_message(description).strip()

    if not category or not description:
        return make_response(
            student_id,
            "Please provide both a category and a description.",
            success=False,
        )

    if len(category) > 100 or len(description) > 2000:
        return make_response(
            student_id,
            "The category or description is too long. Please shorten it.",
            success=False,
        )

    st.session_state["_pending_support_request"] = {
        "student_id": student_id,
        "category": category,
        "description": description,
    }

    record_security_event(
        student_id=student_id,
        action="SUPPORT_REQUEST_CONFIRMATION",
        resource="support_requests",
        outcome="PENDING_CONFIRMATION",
        details="Support request draft prepared.",
    )

    return make_response(
        student_id,
        (
            "### Please Confirm Your Support Request\n\n"
            f"**Category:** {category}\n\n"
            f"**Description:** {description}\n\n"
            "Would you like to submit this request?\n\n"
            "**Reply Yes to submit or No to cancel.**\n\n"
            "No request has been created yet."
        ),
        tool_used="support_request_confirmation",
    )


# ============================================================
# 6. SUPPORT REQUEST CONFIRMATION
# ============================================================

def handle_pending_confirmation(student_id, auth_token, question):
    """Handle Yes/No replies for a pending support request."""

    pending = st.session_state.get("_pending_support_request")

    if not pending:
        return None

    if pending.get("student_id") != student_id:
        st.session_state.pop("_pending_support_request", None)
        return None

    answer = question.lower().strip().rstrip(".!")

    yes_answers = {
        "yes",
        "yes please",
        "confirm",
        "submit",
        "confirm request",
        "submit request",
    }

    no_answers = {
        "no",
        "no thanks",
        "cancel",
        "cancel request",
        "do not submit",
        "don't submit",
    }

    if answer in yes_answers:

        # Clear the pending draft before creating the request.
        st.session_state.pop("_pending_support_request", None)

        result = create_support_request(
            student_id=student_id,
            category=pending["category"],
            description=pending["description"],
            auth_token=auth_token,
        )

        success = result.get("success", False)

        record_security_event(
            student_id=student_id,
            action="SUPPORT_REQUEST_CONFIRMATION",
            resource="support_requests",
            outcome="SUCCESS" if success else "FAILURE",
            details="Student confirmed support request submission.",
        )

        return make_response(
            student_id,
            result.get(
                "message",
                (
                    "Your support request was submitted successfully."
                    if success
                    else "The support request could not be submitted."
                ),
            ),
            success=success,
            tool_used="create_support_request",
            evidence=result,
        )

    if answer in no_answers:

        st.session_state.pop("_pending_support_request", None)

        record_security_event(
            student_id=student_id,
            action="SUPPORT_REQUEST_CONFIRMATION",
            resource="support_requests",
            outcome="CANCELLED",
            details="Student cancelled the support request.",
        )

        return make_response(
            student_id,
            "Your support request was cancelled. No request was created.",
            tool_used="support_request_confirmation",
        )

    # A different message while confirmation is pending.
    return make_response(
        student_id,
        (
            "You have a support request awaiting confirmation.\n\n"
            "Reply **Yes** to submit it or **No** to cancel it."
        ),
        tool_used="support_request_confirmation",
    )


# ============================================================
# 7. MAIN AGENT
# ============================================================

def run_agent(question, student_id, auth_token):
    """Process a student's message securely."""

    # --------------------------------------------------------
    # A. Validate input
    # --------------------------------------------------------

    if not isinstance(question, str) or not question.strip():
        return {
            "success": False,
            "answer": "Please enter a question.",
            "tool_used": None,
        }

    if not student_id:
        return {
            "success": False,
            "answer": "Please sign in again.",
            "tool_used": None,
        }

    # --------------------------------------------------------
    # B. Authenticate
    # --------------------------------------------------------

    verified_id = verify_student(student_id, auth_token)

    if not verified_id:
        return {
            "success": False,
            "answer": (
                "Your session is invalid or your access could not "
                "be verified. Please sign in again."
            ),
            "tool_used": "authorization_check",
        }

    student_id = verified_id
    question = sanitize_message(question).strip()
    question_lower = question.lower().strip()

    # --------------------------------------------------------
    # C. Retrieve conversation history
    # --------------------------------------------------------

    try:
        history = get_conversation_history(
            student_id,
            limit=20,
        )
    except Exception:
        history = []

    previous_user_messages = [
        item.get("content", "")
        for item in history
        if item.get("role") == "user"
    ]

    try:
        save_message(student_id, "user", question)
    except Exception:
        pass

    # --------------------------------------------------------
    # D. Prevent access to other students' records
    # --------------------------------------------------------

    mentioned_ids = re.findall(
        r"\bSTU\d+\b",
        question,
        flags=re.IGNORECASE,
    )

    other_student_ids = [
        value.upper()
        for value in mentioned_ids
        if value.upper() != student_id
    ]

    if other_student_ids:
        record_security_event(
            student_id=student_id,
            action="UNAUTHORIZED_ACCESS_ATTEMPT",
            resource="student_records",
            outcome="DENIED",
            details="Question referenced another student's ID.",
        )

        return make_response(
            student_id,
            (
                "Access denied. You can only access information "
                "belonging to your authenticated student account."
            ),
            success=False,
            tool_used="authorization_check",
        )

    # --------------------------------------------------------
    # E. Handle pending Yes/No confirmation FIRST
    # --------------------------------------------------------

    pending_result = handle_pending_confirmation(
        student_id,
        auth_token,
        question,
    )

    if pending_result is not None:
        return pending_result

    # --------------------------------------------------------
    # F. Greetings
    # --------------------------------------------------------

    greetings = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
    }

    if question_lower in greetings:
        return make_response(
            student_id,
            (
                "Hello! Welcome to the Intelligent Student Support Agent.\n\n"
                "I can help you with:\n\n"
                "- Student details\n"
                "- Fee status\n"
                "- Scholarship status\n"
                "- Institutional policies\n"
                "- Support requests\n"
                "- Previous support requests\n"
                "- Questions about our earlier conversation"
            ),
        )

    # --------------------------------------------------------
    # G. SUPPORT REQUEST DETECTION
    # --------------------------------------------------------

    support_keywords = [
        "support request",
        "raise a ticket",
        "raise a request",
        "raise a fee-related",
        "raise a fee related",
        "create a support request",
        "submit a support request",
        "missing fee receipt",
        "fee receipt is missing",
        "receipt is missing",
        "report an issue",
        "technical issue",
        "login problem",
        "portal problem",
        "unable to access",
        "cannot access",
        "can't access",
        "not working",
        "forgot password",
        "problem with my fees",
        "issue with my fee",
        "issue with my fees",
    ]

    is_support_request = any(
        keyword in question_lower
        for keyword in support_keywords
    )

    has_request_action = any(
        word in question_lower
        for word in [
            "raise",
            "create",
            "submit",
            "report",
            "request",
            "complaint",
        ]
    )

    has_problem_context = any(
        word in question_lower
        for word in [
            "missing",
            "problem",
            "issue",
            "error",
            "not working",
            "receipt",
            "access",
            "login",
        ]
    )

    if (
        is_support_request
        or (has_request_action and has_problem_context)
    ):

        # If category and description are already supplied,
        # create a draft and request confirmation.
        if (
            "category:" in question_lower
            and "description:" in question_lower
        ):
            try:
                category_part, description_part = question.split(
                    ";",
                    1,
                )

                if not category_part.lower().strip().startswith(
                    "category:"
                ):
                    raise ValueError("Category is missing.")

                if not description_part.lower().strip().startswith(
                    "description:"
                ):
                    raise ValueError("Description is missing.")

                category = category_part.split(":", 1)[1].strip()
                description = description_part.split(":", 1)[1].strip()

                return prepare_support_request(
                    student_id,
                    category,
                    description,
                )

            except (ValueError, IndexError):
                return make_response(
                    student_id,
                    (
                        "Please provide the details in this format:\n\n"
                        "Category: Fees; "
                        "Description: My fee receipt is missing"
                    ),
                    success=False,
                )

        # Otherwise, ask for the request details.
        suggested_category = (
            "Fees"
            if any(
                word in question_lower
                for word in [
                    "fee",
                    "fees",
                    "receipt",
                    "payment",
                ]
            )
            else "Technical Issue"
        )

        suggested_description = question.strip()

        return prepare_support_request(
            student_id,
            suggested_category,
            suggested_description,
        )

    # --------------------------------------------------------
    # H. Student details
    # --------------------------------------------------------

    student_detail_keywords = [
        "student details",
        "my details",
        "my program",
        "my course",
        "student information",
        "student record",
        "show my profile",
    ]

    if any(
        keyword in question_lower
        for keyword in student_detail_keywords
    ):

        student, error = fetch_student_record(
            student_id,
            auth_token,
        )

        if error:
            return make_response(
                student_id,
                error,
                success=False,
                tool_used="get_student_record",
            )

        return make_response(
            student_id,
            (
                "### Your Student Details\n\n"
                f"- **Student ID:** {student.get('student_id', 'N/A')}\n"
                f"- **Name:** {student.get('name', 'N/A')}\n"
                f"- **Program:** {student.get('program', 'N/A')}\n"
                f"- **Fee Status:** {student.get('fee_status', 'N/A')}\n"
                f"- **Scholarship Status:** "
                f"{student.get('scholarship_status', 'N/A')}"
            ),
            tool_used="get_student_record",
        )

    # --------------------------------------------------------
    # I. Fee status
    # --------------------------------------------------------

    fee_keywords = [
        "fee status",
        "fees status",
        "tuition status",
        "payment status",
        "have i paid",
        "outstanding fee",
        "outstanding fees",
        "my fee status",
        "my fees status",
    ]

    if any(
        keyword in question_lower
        for keyword in fee_keywords
    ):

        student, error = fetch_student_record(
            student_id,
            auth_token,
        )

        if error:
            return make_response(
                student_id,
                error,
                success=False,
                tool_used="get_student_record",
            )

        return make_response(
            student_id,
            (
                "Your current fee status is: "
                f"{student.get('fee_status', 'Not available')}."
            ),
            tool_used="get_student_record",
        )

    # --------------------------------------------------------
    # J. Scholarship status
    # --------------------------------------------------------

    scholarship_keywords = [
        "scholarship status",
        "my scholarship",
        "scholarship application status",
        "scholarship details",
    ]

    if any(
        keyword in question_lower
        for keyword in scholarship_keywords
    ):

        student, error = fetch_student_record(
            student_id,
            auth_token,
        )

        if error:
            return make_response(
                student_id,
                error,
                success=False,
                tool_used="get_student_record",
            )

        return make_response(
            student_id,
            (
                "Your scholarship status is: "
                f"{student.get('scholarship_status', 'Not available')}."
            ),
            tool_used="get_student_record",
        )

    # --------------------------------------------------------
    # K. Previous support requests
    # --------------------------------------------------------

    history_keywords = [
        "my support requests",
        "my support request history",
        "my tickets",
        "previous requests",
        "request history",
        "previous support requests",
        "show my requests",
        "my request history",
    ]

    if any(
        keyword in question_lower
        for keyword in history_keywords
    ):

        result = get_student_requests_for_user(
            student_id=student_id,
            auth_token=auth_token,
        )

        if not result.get("success"):
            return make_response(
                student_id,
                result.get(
                    "message",
                    "Unable to retrieve your support requests.",
                ),
                success=False,
                tool_used="get_student_requests_for_user",
            )

        requests = result.get("requests", [])

        if not requests:
            return make_response(
                student_id,
                "You don't have any support requests yet.",
                tool_used="get_student_requests_for_user",
            )

        lines = ["### Your Support Requests"]

        for request in requests:
            lines.append(
                f"- **Request ID:** {request.get('request_id', 'N/A')}\n"
                f"  - Category: {request.get('category', 'N/A')}\n"
                f"  - Description: {request.get('description', 'N/A')}\n"
                f"  - Status: {request.get('status', 'N/A')}\n"
                f"  - Created: {request.get('created_at', 'N/A')}"
            )

        return make_response(
            student_id,
            "\n\n".join(lines),
            tool_used="get_student_requests_for_user",
        )

    # --------------------------------------------------------
    # L. Conversation memory
    # --------------------------------------------------------

    # Recall a simple personal fact from previous user messages.
    # Only searches the authenticated student's own saved history.
    favorite_subject_match = re.search(
        r"\bmy favorite subject is ([^.!?\n]+)",
        " ".join(previous_user_messages),
        flags=re.IGNORECASE,
    )

    if any(
        phrase in question_lower
        for phrase in [
            "what is my favorite subject",
            "what's my favorite subject",
            "which is my favorite subject",
        ]
    ):
        if favorite_subject_match:
            favorite_subject = favorite_subject_match.group(1).strip()

            return make_response(
                student_id,
                (
                    "You previously told me that your favorite "
                    f"subject is {favorite_subject}."
                ),
                tool_used="get_conversation_history",
            )

        return make_response(
            student_id,
            (
                "I couldn't find your favorite subject in our saved "
                "conversation history. Please tell me again."
            ),
            tool_used="get_conversation_history",
        )

    memory_keywords = [
        "what did i ask",
        "what was my previous question",
        "what did i tell you",
        "what did we discuss",
        "what was discussed earlier",
        "what was my last question",
        "remember our previous conversation",
    ]

    if any(
        keyword in question_lower
        for keyword in memory_keywords
    ):

        if previous_user_messages:
            return make_response(
                student_id,
                (
                    "Your previous question was:\n\n"
                    f"> {previous_user_messages[-1]}"
                ),
                tool_used="get_conversation_history",
            )

        return make_response(
            student_id,
            (
                "I couldn't find an earlier question in your saved "
                "conversation history."
            ),
            tool_used="get_conversation_history",
        )

    # --------------------------------------------------------
    # M. Institutional policy retrieval
    # --------------------------------------------------------

    try:
        policy_result = search_policy(question)
    except Exception:
        policy_result = {"success": False}

    if policy_result and policy_result.get("success"):
        return make_response(
            student_id,
            policy_result.get(
                "answer",
                "No policy answer was returned.",
            ),
            tool_used="search_policy",
            sources=policy_result.get("sources", []),
        )

    # --------------------------------------------------------
    # N. Default response
    # --------------------------------------------------------

    return make_response(
        student_id,
        (
            "I can help you with:\n\n"
            "- Student details\n"
            "- Fee status\n"
            "- Scholarship status\n"
            "- Institutional policies\n"
            "- Creating support requests\n"
            "- Checking previous support requests\n"
            "- Questions about our earlier conversation\n\n"
            "Please describe what you need help with."
        ),
    )


# ============================================================
# 8. DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    print(
        "Run this agent through Streamlit using:\n"
        "streamlit run app.py"
    )
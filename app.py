
import streamlit as st

from agent import run_agent
from database import authenticate_student, initialize_database
from auth_context import create_auth_context, clear_auth_context


# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="Intelligent Student Support Agent",
    page_icon="🎓",
    layout="centered"
)

initialize_database()

st.title("🎓 Intelligent Student Support Agent")
st.caption(
    "Your assistant for student fees, scholarships, "
    "institutional policies, and support requests."
)


# ---------------------------------------------------------
# SESSION INITIALIZATION
# ---------------------------------------------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "student_id" not in st.session_state:
    st.session_state.student_id = None

if "messages" not in st.session_state:
    st.session_state.messages = []


# ---------------------------------------------------------
# LOGIN SCREEN
# ---------------------------------------------------------

if not st.session_state.authenticated:

    st.subheader("Student Login")

    st.info(
        "Sign in using a student account that has already "
        "been registered."
    )

    with st.form("student_login_form"):

        login_student_id = st.text_input(
            "Student ID",
            placeholder="Enter your student ID"
        )

        login_password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password"
        )

        login_submitted = st.form_submit_button(
            "Sign in",
            use_container_width=True
        )

    if login_submitted:

        if not login_student_id.strip() or not login_password:
            st.warning(
                "Please enter both your student ID and password."
            )

        else:
            try:
                result = authenticate_student(
                    login_student_id.strip(),
                    login_password
                )

                if result.get("success"):

                    # Use the ID returned by successful authentication.
                    authenticated_student_id = result["student_id"]

                    # Create a new authentication context.
                    create_auth_context(authenticated_student_id)

                    st.session_state.student_id = (
                        authenticated_student_id
                    )
                    st.session_state.authenticated = True
                    st.session_state.messages = []

                    st.success("Login successful!")
                    st.rerun()

                else:
                    st.error(
                        "Login failed. Check your credentials "
                        "and try again."
                    )

            except Exception:
                st.error(
                    "Unable to complete login. Please try again."
                )

    # Stop until the student logs in.
    st.stop()


# ---------------------------------------------------------
# AUTHENTICATED STUDENT SESSION
# ---------------------------------------------------------

student_id = st.session_state.student_id

if not student_id:

    clear_auth_context()

    st.session_state.authenticated = False
    st.session_state.student_id = None
    st.session_state.messages = []

    st.rerun()

# Retrieve the authentication token from the current session.
auth_token = st.session_state.get("_auth_context_token")

# If the token is missing, require the student to log in again.
if not auth_token:

    clear_auth_context()

    st.session_state.authenticated = False
    st.session_state.student_id = None
    st.session_state.messages = []

    st.warning("Your session has expired. Please sign in again.")
    st.rerun()

st.success(f"Signed in as student: {student_id}")


# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------

if st.button("Log out"):

    clear_auth_context()

    st.session_state.authenticated = False
    st.session_state.student_id = None
    st.session_state.messages = []

    st.rerun()


# ---------------------------------------------------------
# CHAT HISTORY
# ---------------------------------------------------------

for message in st.session_state.messages:

    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# ---------------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------------

question = st.chat_input("Ask your question here...")

if question:

    st.session_state.messages.append({
        "role": "user",
        "content": question
    })

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):

        with st.spinner("Thinking..."):

            try:
                result = run_agent(
                    question,
                    student_id,
                    auth_token
                )

                answer = result.get(
                    "answer",
                    "Sorry, I could not generate a response."
                )

                st.markdown(answer)

                tool_used = result.get("tool_used")

                if tool_used:
                    st.caption(f"Tool used: {tool_used}")

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer
                })

            except Exception:
                st.error(
                    "Something went wrong while processing "
                    "your question. Please try again."
                )

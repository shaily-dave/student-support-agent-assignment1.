"""
Database Module
Intelligent Student Support Agent

Features:
- Student authentication
- Secure password hashing
- Support request management
- Student-specific request retrieval
- Audit logging for security events
"""

import sqlite3
import hashlib
import hmac
import secrets
from pathlib import Path


# ---------------------------------------------------------
# DATABASE CONFIGURATION
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "student_support.db"

PBKDF2_ITERATIONS = 600_000


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def get_connection():
    """Create a connection to the SQLite database."""

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=10
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ---------------------------------------------------------
# DATABASE INITIALIZATION
# ---------------------------------------------------------

def initialize_database():
    """Create the required database tables."""

    connection = get_connection()

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS support_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Stores password hashes, never plaintext passwords.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS student_accounts (
                student_id TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Records authentication and authorization decisions.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_student_id TEXT,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                outcome TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_support_student
            ON support_requests(student_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_actor
            ON audit_log(actor_student_id, audit_id)
        """)

        connection.commit()

    finally:
        connection.close()


# ---------------------------------------------------------
# STUDENT ID NORMALIZATION
# ---------------------------------------------------------

def normalize_student_id(student_id):
    """Normalize student IDs consistently."""

    if not isinstance(student_id, str):
        return ""

    return student_id.strip().upper()


# ---------------------------------------------------------
# PASSWORD HASHING
# ---------------------------------------------------------

def _hash_password(password, salt):
    """Hash a password using PBKDF2-HMAC-SHA256."""

    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS
    ).hex()


# ---------------------------------------------------------
# CREATE STUDENT LOGIN
# ---------------------------------------------------------

def create_student_account(student_id, password):
    """
    Create a student login.

    The student must already exist in data/students.csv.
    Existing accounts cannot be silently overwritten.
    """

    initialize_database()

    normalized_id = normalize_student_id(student_id)

    if not normalized_id:
        return {
            "success": False,
            "message": "A valid student ID is required."
        }

    if not isinstance(password, str) or len(password) < 12:
        return {
            "success": False,
            "message": (
                "Password must contain at least 12 characters."
            )
        }

    # Confirm that this student exists in the institution's
    # sample student data before creating an account.
    import csv

    student_file = BASE_DIR / "data" / "students.csv"

    if not student_file.exists():
        return {
            "success": False,
            "message": "Student data file is unavailable."
        }

    with student_file.open(
        "r",
        newline="",
        encoding="utf-8"
    ) as file:
        reader = csv.DictReader(file)

        student_exists = any(
            normalize_student_id(row.get("student_id", ""))
            == normalized_id
            for row in reader
        )

    if not student_exists:
        return {
            "success": False,
            "message": "Student record not found."
        }

    salt = secrets.token_bytes(16)
    password_hash = _hash_password(password, salt)

    connection = get_connection()

    try:
        connection.execute("""
            INSERT INTO student_accounts (
                student_id,
                password_hash,
                password_salt
            )
            VALUES (?, ?, ?)
        """, (
            normalized_id,
            password_hash,
            salt.hex()
        ))

        connection.commit()

        log_audit_event(
            actor_student_id=normalized_id,
            action="CREATE_STUDENT_ACCOUNT",
            resource="student_accounts",
            outcome="SUCCESS",
            details="Student account created."
        )

        return {
            "success": True,
            "message": "Student account created successfully."
        }

    except sqlite3.IntegrityError:
        return {
            "success": False,
            "message": (
                "An account already exists for this student."
            )
        }

    except sqlite3.Error:
        return {
            "success": False,
            "message": "Unable to create the student account."
        }

    finally:
        connection.close()


# ---------------------------------------------------------
# AUTHENTICATE STUDENT
# ---------------------------------------------------------

def authenticate_student(student_id, password):
    """Verify student credentials and return authentication status."""

    initialize_database()

    normalized_id = normalize_student_id(student_id)

    if not normalized_id or not isinstance(password, str):
        log_audit_event(
            actor_student_id=normalized_id or None,
            action="LOGIN",
            resource="student_accounts",
            outcome="DENIED",
            details="Invalid login input."
        )

        return {
            "success": False,
            "message": "Invalid student ID or password."
        }

    connection = get_connection()

    try:
        row = connection.execute("""
            SELECT password_hash, password_salt
            FROM student_accounts
            WHERE student_id = ?
        """, (normalized_id,)).fetchone()

        if row is None:
            log_audit_event(
                actor_student_id=normalized_id,
                action="LOGIN",
                resource="student_accounts",
                outcome="DENIED",
                details="Invalid credentials."
            )

            return {
                "success": False,
                "message": "Invalid student ID or password."
            }

        salt = bytes.fromhex(row["password_salt"])

        candidate_hash = _hash_password(password, salt)

        if not hmac.compare_digest(
            candidate_hash,
            row["password_hash"]
        ):
            log_audit_event(
                actor_student_id=normalized_id,
                action="LOGIN",
                resource="student_accounts",
                outcome="DENIED",
                details="Invalid credentials."
            )

            return {
                "success": False,
                "message": "Invalid student ID or password."
            }

        log_audit_event(
            actor_student_id=normalized_id,
            action="LOGIN",
            resource="student_accounts",
            outcome="SUCCESS",
            details="Student authenticated."
        )

        return {
            "success": True,
            "student_id": normalized_id,
            "message": "Authentication successful."
        }

    finally:
        connection.close()


# ---------------------------------------------------------
# AUDIT LOGGING
# ---------------------------------------------------------

def log_audit_event(
    actor_student_id,
    action,
    resource,
    outcome,
    details=""
):
    """Record a security or application event."""

    initialize_database()

    connection = get_connection()

    try:
        connection.execute("""
            INSERT INTO audit_log (
                actor_student_id,
                action,
                resource,
                outcome,
                details
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            normalize_student_id(actor_student_id) or None,
            str(action)[:100],
            str(resource)[:200],
            str(outcome)[:50],
            str(details)[:1000]
        ))

        connection.commit()

    finally:
        connection.close()


def get_audit_logs(limit=100):
    """Retrieve recent audit records for demonstration."""

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("Limit must be an integer.")

    if not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000.")

    initialize_database()

    connection = get_connection()

    try:
        rows = connection.execute("""
            SELECT
                audit_id,
                actor_student_id,
                action,
                resource,
                outcome,
                details,
                created_at
            FROM audit_log
            ORDER BY audit_id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


# ---------------------------------------------------------
# SUPPORT REQUEST CREATION
# ---------------------------------------------------------

def save_support_request(student_id, category, description):
    """Save a support request for a student."""

    initialize_database()

    normalized_id = normalize_student_id(student_id)

    if not normalized_id:
        return {
            "success": False,
            "message": "A student ID is required."
        }

    if not isinstance(category, str) or not category.strip():
        return {
            "success": False,
            "message": "Please provide an issue category."
        }

    if not isinstance(description, str) or not description.strip():
        return {
            "success": False,
            "message": "Please describe the issue."
        }

    connection = get_connection()

    try:
        cursor = connection.execute("""
            INSERT INTO support_requests (
                student_id,
                category,
                description
            )
            VALUES (?, ?, ?)
        """, (
            normalized_id,
            category.strip(),
            description.strip()
        ))

        connection.commit()

        request_id = cursor.lastrowid

        log_audit_event(
            actor_student_id=normalized_id,
            action="CREATE_SUPPORT_REQUEST",
            resource=f"support_request:{request_id}",
            outcome="SUCCESS",
            details="Support request created."
        )

        return {
            "success": True,
            "request_id": request_id,
            "message": "Support request saved successfully."
        }

    except sqlite3.Error:
        return {
            "success": False,
            "message": "Unable to save the support request."
        }

    finally:
        connection.close()


# ---------------------------------------------------------
# RETRIEVE STUDENT SUPPORT REQUESTS
# ---------------------------------------------------------

def get_student_requests(student_id):
    """Retrieve support requests for the specified student ID."""

    initialize_database()

    normalized_id = normalize_student_id(student_id)

    if not normalized_id:
        return []

    connection = get_connection()

    try:
        rows = connection.execute("""
            SELECT
                request_id,
                student_id,
                category,
                description,
                status,
                created_at
            FROM support_requests
            WHERE student_id = ?
            ORDER BY request_id DESC
        """, (normalized_id,)).fetchall()

        return [dict(row) for row in rows]

    finally:
        connection.close()


# ---------------------------------------------------------
# RUN DIRECTLY
# ---------------------------------------------------------

if __name__ == "__main__":
    initialize_database()

    print("Database initialized successfully.")
    print(f"Database location: {DB_PATH}")
    print("Authentication and audit tables are ready.")
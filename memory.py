"""
Conversation Memory
Intelligent Student Support Agent

Stores and retrieves conversation history using SQLite.
Sensitive credentials are redacted before being stored.
"""

import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


# Use the existing project database.
DB_PATH = Path(__file__).resolve().parent / "student_support.db"


# Patterns for identifying sensitive information.
SENSITIVE_PATTERNS = [
    # Passwords, PINs and passcodes
    re.compile(
        r"""(?P<label>\b(?:password|passwd|passcode|pin)\b)
        \s*(?:is|:|=|->|-)\s*
        (?P<value>"[^"]*"|'[^']*'|[^\r\n.!?;,]+)""",
        re.IGNORECASE | re.VERBOSE
    ),

    # OTPs and verification codes, including values provided without "is".
    re.compile(
        r"""(?P<label>\b(?:otp(?:\s+code)?|
        one[- ]time(?:\s+password)?|
        verification\s+code|
        security\s+code)\b)
        \s*(?:(?:is|:|=|->|-)\s*|\s+)
        (?P<value>"[^"]*"|'[^']*'|[^\r\n.!?;,]+)""",
        re.IGNORECASE | re.VERBOSE
    ),

    # API keys, access tokens and secrets
    re.compile(
        r"""(?P<label>\b(?:api[\s_-]*key|
        access[\s_-]*token|
        secret)\b)
        \s*(?:is|:|=|->|-)\s*
        (?P<value>"[^"]*"|'[^']*'|[^\r\n.!?;,]+)""",
        re.IGNORECASE | re.VERBOSE
    )
]


def sanitize_message(content: str) -> str:
    """
    Redact sensitive values before a message is stored.
    """

    if not isinstance(content, str):
        return ""

    sanitized_content = content

    for pattern in SENSITIVE_PATTERNS:
        sanitized_content = pattern.sub(
            lambda match: f"{match.group('label')} [REDACTED]",
            sanitized_content
        )

    return sanitized_content.strip()


def initialize_memory() -> None:
    """Create the conversation memory table if it does not exist."""

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversation_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_student
            ON conversation_memory(student_id, id)
        """)


def save_message(student_id: str, role: str, content: str) -> dict:
    """Save a conversation message after removing sensitive values."""

    if not student_id or not student_id.strip():
        return {
            "success": False,
            "message": "Student ID is required."
        }

    if role not in ("user", "assistant"):
        return {
            "success": False,
            "message": "Role must be 'user' or 'assistant'."
        }

    if not isinstance(content, str) or not content.strip():
        return {
            "success": False,
            "message": "Message content cannot be empty."
        }

    # IMPORTANT: Sanitize before inserting into the database.
    original_content = content.strip()
    safe_content = sanitize_message(original_content)

    initialize_memory()

    timestamp = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            """
            INSERT INTO conversation_memory
                (student_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                student_id.strip(),
                role,
                safe_content,
                timestamp
            )
        )

        message_id = cursor.lastrowid

    return {
        "success": True,
        "message_id": message_id,
        "redacted": safe_content != original_content,
        "message": "Conversation message saved securely."
    }


def get_conversation_history(
    student_id: str,
    limit: int = 20
) -> list:
    """Retrieve recent conversation messages for a student."""

    if not student_id or not student_id.strip():
        return []

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("Limit must be a positive integer.")

    initialize_memory()

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row

        rows = connection.execute(
            """
            SELECT id, student_id, role, content, created_at
            FROM conversation_memory
            WHERE student_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (student_id.strip(), limit)
        ).fetchall()

    # Return messages in chronological order.
    return [dict(row) for row in reversed(rows)]


def clear_conversation_history(student_id: str) -> dict:
    """Delete conversation history for a specific student ID."""

    if not student_id or not student_id.strip():
        return {
            "success": False,
            "message": "Student ID is required."
        }

    initialize_memory()

    with sqlite3.connect(DB_PATH) as connection:
        cursor = connection.execute(
            """
            DELETE FROM conversation_memory
            WHERE student_id = ?
            """,
            (student_id.strip(),)
        )

        deleted_count = cursor.rowcount

    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": "Conversation history cleared successfully."
    }


def sanitize_existing_memory() -> int:
    """
    Clean previously stored messages that may contain sensitive values.
    Returns the number of updated messages.
    """

    initialize_memory()

    updated_count = 0

    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute(
            """
            SELECT id, content
            FROM conversation_memory
            """
        ).fetchall()

        for message_id, content in rows:
            safe_content = sanitize_message(content)

            if safe_content != content:
                connection.execute(
                    """
                    UPDATE conversation_memory
                    SET content = ?
                    WHERE id = ?
                    """,
                    (safe_content, message_id)
                )

                updated_count += 1

    return updated_count


# Allow this file to be tested independently.
if __name__ == "__main__":
    initialize_memory()

    cleaned_count = sanitize_existing_memory()

    print("Conversation memory initialized successfully.")
    print(f"Database location: {DB_PATH}")
    print(f"Previously stored messages cleaned: {cleaned_count}")
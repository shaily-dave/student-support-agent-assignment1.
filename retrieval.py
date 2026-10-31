"""
Student Policy Retrieval
Intelligent Student Support Agent

Retrieves the most relevant policy section using keyword matching.
"""

import re
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parent / "data" / "student_policy.txt"


def load_policy() -> str:
    """Load the student policy document."""
    if not POLICY_PATH.exists():
        return ""
    return POLICY_PATH.read_text(encoding="utf-8")


def split_into_chunks(text: str) -> list:
    """Split the policy document into numbered sections."""
    if not text.strip():
        return []

    # Split at headings such as '1. FEE PAYMENT' or '3. SCHOLARSHIPS'.
    sections = re.split(
        r"(?m)(?=^\s*\d+\.\s+[A-Z][A-Z\s&/-]*\s*$)",
        text.strip()
    )

    return [section.strip() for section in sections if section.strip()]


def search_policy(question: str, top_k: int = 3) -> dict:
    """Retrieve policy sections relevant to a question."""

    if not isinstance(question, str) or not question.strip():
        return {
            "success": False,
            "answer": "Please enter a question.",
            "sources": []
        }

    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        return {
            "success": False,
            "answer": "top_k must be a positive integer.",
            "sources": []
        }

    policy_text = load_policy()

    if not policy_text.strip():
        return {
            "success": False,
            "answer": "The student policy document is unavailable.",
            "sources": []
        }

    chunks = split_into_chunks(policy_text)

    # Map common expressions to the policy topics they represent.
    topic_keywords = {
        "FEE PAYMENT": {
            "fee", "fees", "payment", "payments", "pay",
            "paid", "failed", "failure", "transaction",
            "accounts", "portal", "duplicate", "refund"
        },
        "PAYMENT DEADLINES": {
            "deadline", "deadlines", "extension", "due",
            "date", "dates", "late", "portal", "unavailable"
        },
        "SCHOLARSHIPS": {
            "scholarship", "scholarships", "grant", "grants",
            "approved", "approval", "review", "application"
        },
        "COURSE CHANGES": {
            "course", "courses", "programme", "program",
            "change", "changes", "academic"
        },
        "SUPPORT REQUESTS": {
            "support", "request", "requests", "help",
            "issue", "assistance"
        },
        "INFORMATION LIMITATIONS": {
            "unknown", "information", "policy", "policies",
            "office", "contact"
        }
    }

    question_words = {
        word.lower()
        for word in re.findall(r"\b[a-zA-Z]+\b", question)
    }

    # Score each section based on its heading and matching terms.
    scored_chunks = []

    for index, chunk in enumerate(chunks):
        lines = chunk.splitlines()
        heading = lines[0].strip().upper() if lines else ""

        score = 0

        for topic, keywords in topic_keywords.items():
            if topic in heading:
                score += len(question_words.intersection(keywords)) * 3

        # Give extra weight to meaningful matches in the section text.
        content_words = {
            word.lower()
            for word in re.findall(r"\b[a-zA-Z]+\b", chunk)
        }

        score += len(question_words.intersection(content_words))

        if score > 0:
            scored_chunks.append({
                "section": heading,
                "score": score,
                "content": chunk
            })

    scored_chunks.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    if not scored_chunks:
        return {
            "success": False,
            "answer": (
                "I could not find relevant information in the "
                "available student policy document. Please contact "
                "the appropriate institutional office."
            ),
            "sources": []
        }

    # Return only the best-matching section by default.
    best_score = scored_chunks[0]["score"]
    results = [
        item for item in scored_chunks
        if item["score"] == best_score
    ][:top_k]

    answer_parts = [
        f"**Policy information — {item['section']}:**\n{item['content']}"
        for item in results
    ]

    return {
        "success": True,
        "answer": "\n\n".join(answer_parts),
        "sources": [
            {
                "document": POLICY_PATH.name,
                "section": item["section"]
            }
            for item in results
        ]
    }


if __name__ == "__main__":
    questions = [
        "I need help with my fee payment.",
        "What is my scholarship status?",
        "How do I request a course change?",
        "What should I do if the payment portal is unavailable?"
    ]

    for question in questions:
        result = search_policy(question)
        print(f"\nQuestion: {question}")
        print(result["answer"])
        
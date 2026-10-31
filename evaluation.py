"""
Evaluation Framework
Intelligent Student Support Agent
"""

import time
from agent import run_agent


TEST_CASES = [
    {
        "name": "Greeting",
        "question": "Hello",
        "expected_tool": None,
        "expected_text": "welcome"
    },
    {
        "name": "Student details",
        "question": "Show me my student details",
        "expected_tool": "get_student_record",
        "expected_text": "student details"
    },
    {
        "name": "Fee status",
        "question": "What is my fee status?",
        "expected_tool": "get_student_record",
        "expected_text": "fee status"
    },
    {
        "name": "Scholarship status",
        "question": "What is my scholarship status?",
        "expected_tool": "get_student_record",
        "expected_text": "scholarship status"
    },
    {
        "name": "Fee payment policy",
        "question": "What should I do if my fee payment fails?",
        "expected_tool": "search_policy",
        "expected_text": "accounts office"
    },
    {
        "name": "Course change policy",
        "question": "What is the policy for course changes?",
        "expected_tool": "search_policy",
        "expected_text": "academic office"
    }
]


def run_evaluation(student_id="STU001"):
    """Run test cases and report basic evaluation results."""

    results = []

    for test in TEST_CASES:
        start_time = time.perf_counter()

        try:
            response = run_agent(
                test["question"],
                student_id
            )

            elapsed = time.perf_counter() - start_time

            answer = response.get("answer", "")
            tool_used = response.get("tool_used")

            correct_tool = tool_used == test["expected_tool"]
            correct_text = test["expected_text"] in answer.lower()

            passed = correct_tool and correct_text

            results.append({
                "test": test["name"],
                "passed": passed,
                "expected_tool": test["expected_tool"],
                "actual_tool": tool_used,
                "expected_text": test["expected_text"],
                "response": answer,
                "latency_seconds": round(elapsed, 4)
            })

        except Exception as error:
            results.append({
                "test": test["name"],
                "passed": False,
                "error": str(error)
            })

    total = len(results)
    passed_count = sum(
        1 for result in results if result["passed"]
    )

    print("\nINTELLIGENT STUDENT SUPPORT AGENT")
    print("=" * 45)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"

        print(f"\n[{status}] {result['test']}")

        if "error" in result:
            print("Error:", result["error"])
        else:
            print("Expected tool:", result["expected_tool"])
            print("Actual tool:", result["actual_tool"])
            print("Latency:", result["latency_seconds"], "seconds")

            if not result["passed"]:
                print("Response:", result["response"])

    accuracy = (passed_count / total * 100) if total else 0

    print("\n" + "=" * 45)
    print(f"Tests passed: {passed_count}/{total}")
    print(f"Evaluation accuracy: {accuracy:.2f}%")

    return results


if __name__ == "__main__":
    run_evaluation()
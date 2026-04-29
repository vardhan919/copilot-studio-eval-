import time
import logging
from typing import Optional
from .client import CopilotStudioClient
from . import reporter

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {"Completed", "Failed", "Cancelled", "Error"}


def resolve_test_set(
    client: CopilotStudioClient,
    test_set_id: Optional[str] = None,
    test_set_name: Optional[str] = None,
) -> dict:
    if test_set_id:
        ts = client.get_test_set(test_set_id)
        logger.info(f"Resolved test set by ID: {ts.get('displayName')} ({test_set_id})")
        return ts

    test_sets = client.get_test_sets()
    if not test_sets:
        raise RuntimeError("No test sets found for this agent. Create one in Copilot Studio first.")

    if test_set_name:
        matches = [ts for ts in test_sets if ts.get("displayName") == test_set_name]
        if not matches:
            available = [ts.get("displayName") for ts in test_sets]
            raise RuntimeError(f"Test set '{test_set_name}' not found. Available: {available}")
        logger.info(f"Resolved test set by name: {matches[0].get('displayName')}")
        return matches[0]

    active = [ts for ts in test_sets if ts.get("state") == "Active"]
    if len(active) == 1:
        logger.info(f"Auto-selected only active test set: {active[0].get('displayName')}")
        return active[0]

    names = [ts.get("displayName") for ts in test_sets]
    raise RuntimeError(
        f"Multiple test sets found. Set TEST_SET_ID or TEST_SET_NAME. Available: {names}"
    )


def run_evaluation(
    client: CopilotStudioClient,
    test_set_id: str,
    poll_interval: int = 10,
    timeout: int = 300,
    mcs_connection_id: Optional[str] = None,
) -> dict:
    logger.info(f"Starting evaluation for test set: {test_set_id}")
    run = client.start_run(test_set_id, mcs_connection_id)
    run_id = run.get("runId")
    if not run_id:
        raise RuntimeError(f"No runId in response: {run}")
    logger.info(f"Run started — runId: {run_id}")

    elapsed = 0
    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        details = client.get_run(run_id)
        state = details.get("state", "Unknown")
        processed = details.get("testCasesProcessed", 0)
        total = details.get("totalTestCases", "?")
        logger.info(f"[{elapsed}s elapsed] state={state} | progress={processed}/{total}")

        if state in _TERMINAL_STATES:
            return details

    raise TimeoutError(
        f"Evaluation did not complete within {timeout}s. Run ID: {run_id} — check Copilot Studio for results."
    )


def print_results(run: dict, test_set_name: str = "") -> bool:
    return reporter.print_results(run, test_set_name)

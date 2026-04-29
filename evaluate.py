import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv
from src.auth import get_token
from src.client import CopilotStudioClient
from src.runner import resolve_test_set, run_evaluation
from src.reporter import analyze, print_results, print_overall_summary, write_json, write_junit_xml

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required env var '{key}' is not set. Check your .env file.")
    return val


def _csv(key: str) -> list[str]:
    return [v.strip() for v in (os.getenv(key) or "").split(",") if v.strip()]


def main():
    tenant_id      = _require("AZURE_TENANT_ID")
    client_id      = os.getenv("CLIENT_ID")
    environment_id = _require("ENVIRONMENT_ID")
    bot_id         = _require("BOT_ID")
    poll_interval  = int(os.getenv("POLL_INTERVAL_SEC", "10"))
    timeout        = int(os.getenv("POLL_TIMEOUT_SEC", "300"))

    ts_ids   = _csv("TEST_SET_ID")
    ts_names = _csv("TEST_SET_NAME")

    logging.info("Authenticating...")
    token = get_token(tenant_id, client_id)
    logging.info("Authentication successful.")

    client = CopilotStudioClient(token, environment_id, bot_id)

    if ts_ids:
        test_sets = [resolve_test_set(client, test_set_id=tid) for tid in ts_ids]
    elif ts_names:
        test_sets = [resolve_test_set(client, test_set_name=name) for name in ts_names]
    else:
        test_sets = [resolve_test_set(client)]  # auto-select if only one active test set exists

    logging.info(f"Running {len(test_sets)} test set(s): {[ts.get('displayName') for ts in test_sets]}")

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_rows: list[tuple[str, dict]] = []
    all_green = True

    for ts in test_sets:
        ts_name = ts.get("displayName", "unknown")
        run = run_evaluation(client, ts["id"], poll_interval, timeout)
        passed = print_results(run, ts_name)
        all_green = all_green and passed

        stats = analyze(run)
        summary_rows.append((ts_name, stats))

        slug = ts_name.lower().replace(" ", "_")[:40]
        base = os.path.join("results", f"{run_ts}_{slug}")
        write_json(run, stats, f"{base}.json")
        write_junit_xml(run, stats, f"{base}_junit.xml", ts_name)
        logging.info(f"Results saved -> {base}.json  |  {base}_junit.xml")

    if len(summary_rows) > 1:
        print_overall_summary(summary_rows)

    sys.exit(0 if all_green else 1)


if __name__ == "__main__":
    try:
        main()
    except (EnvironmentError, RuntimeError, TimeoutError) as e:
        logging.error(str(e))
        sys.exit(2)

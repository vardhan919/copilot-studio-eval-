import os
import sys
import logging
from datetime import datetime
from dotenv import load_dotenv
from src.auth import get_token
from src.client import CopilotStudioClient
from src.runner import resolve_test_set, run_evaluation
from src.reporter import analyze, print_results, write_json, write_junit_xml

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


def main():
    tenant_id      = _require("AZURE_TENANT_ID")
    client_id      = os.getenv("CLIENT_ID")
    environment_id = _require("ENVIRONMENT_ID")
    bot_id         = _require("BOT_ID")
    test_set_id    = os.getenv("TEST_SET_ID")
    test_set_name  = os.getenv("TEST_SET_NAME")
    poll_interval  = int(os.getenv("POLL_INTERVAL_SEC", "10"))
    timeout        = int(os.getenv("POLL_TIMEOUT_SEC", "300"))

    logging.info("Authenticating...")
    token = get_token(tenant_id, client_id)
    logging.info("Authentication successful.")

    client = CopilotStudioClient(token, environment_id, bot_id)

    test_set = resolve_test_set(client, test_set_id=test_set_id, test_set_name=test_set_name)
    logging.info(f"Running test set: {test_set.get('displayName')}")

    run = run_evaluation(client, test_set["id"], poll_interval, timeout)

    passed = print_results(run, test_set.get("displayName", ""))

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = test_set.get("displayName", "run").lower().replace(" ", "_")[:40]
    base = os.path.join("results", f"{run_ts}_{slug}")
    stats = analyze(run)
    write_json(run, stats, f"{base}.json")
    write_junit_xml(run, stats, f"{base}_junit.xml", test_set.get("displayName", ""))
    logging.info(f"Results saved -> {base}.json  |  {base}_junit.xml")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    try:
        main()
    except (EnvironmentError, RuntimeError, TimeoutError) as e:
        logging.error(str(e))
        sys.exit(2)

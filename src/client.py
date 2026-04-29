import requests
from typing import Optional

_API_VERSION = "2024-10-01"
_BASE = "https://api.powerplatform.com/copilotstudio/environments/{env_id}/bots/{bot_id}/api/makerevaluation"


class CopilotStudioClient:
    def __init__(self, token: str, environment_id: str, bot_id: str):
        self._base = _BASE.format(env_id=environment_id, bot_id=bot_id)
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})
        self._params = {"api-version": _API_VERSION}

    def _get(self, path: str, extra_params: Optional[dict] = None) -> dict:
        params = {**self._params, **(extra_params or {})}
        r = self._session.get(f"{self._base}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def get_test_sets(self) -> list:
        return self._get("/testsets").get("value", [])

    def get_test_set(self, test_set_id: str) -> dict:
        return self._get(f"/testsets/{test_set_id}")

    def start_run(self, test_set_id: str, mcs_connection_id: Optional[str] = None) -> dict:
        params = {**self._params}
        if mcs_connection_id:
            params["mcsConnectionId"] = mcs_connection_id
        r = self._session.post(f"{self._base}/testsets/{test_set_id}/run", params=params, json={})
        r.raise_for_status()
        return r.json()

    def get_run(self, run_id: str) -> dict:
        return self._get(f"/testruns/{run_id}")

    def get_runs(self) -> list:
        return self._get("/testruns").get("value", [])

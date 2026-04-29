# Copilot Studio Agent Evaluation via REST API

A Python script to programmatically trigger Copilot Studio agent evaluations, poll for results, and get structured pass/fail output — no portal clicks required.

## Useful Links

- [About agent evaluation — Microsoft Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-intro)
- [Evaluation REST API reference — Microsoft Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-rest-api)
- [Run tests and view results — Microsoft Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-results)
- [Generate and import test sets — Microsoft Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/analytics-agent-evaluation-create)
- [MSAL Python library](https://github.com/AzureAD/microsoft-authentication-library-for-python)

---

## How It Works

```
python evaluate.py
        │
        ▼
1. Auth  — Azure CLI token if logged in, else MSAL interactive browser
        │
        ▼
2. Resolve test set  — by name or ID from .env → GET /testsets
        │
        ▼
3. Trigger run  — POST /testsets/{id}/run → returns runId
        │
        ▼
4. Poll  — GET /testruns/{runId} every 10s until state != Running
        │
        ▼
5. Print results  — per test case: metrics, AI reasons, pass/fail
        │
        ▼
6. Exit  — 0 (all passed) | 1 (failures) | 2 (config error)
```

---

## Setup

### 1. Create an Entra ID app registration

- Type: **Public client** (mobile/desktop), not web
- Redirect URI: `http://localhost`
- API permission: `CopilotStudio.MakerOperations.Read` (delegated) on the Power Platform API
- Grant admin consent

> You need a tenant where you have admin rights. Client secrets are blocked in many enterprise tenants — this script uses delegated auth (your own identity) which avoids that entirely.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure `.env`

Copy `.env.template` to `.env` and fill in your values:

```env
AZURE_TENANT_ID=<your-entra-tenant-id>
CLIENT_ID=<your-app-registration-client-id>
ENVIRONMENT_ID=<your-power-platform-environment-id>
BOT_ID=<your-copilot-studio-bot-id>

# Single test set
TEST_SET_NAME=My Test Set

# Multiple test sets (comma-separated) — all run in sequence
# TEST_SET_NAME=Test Set One, Test Set Two, Test Set Three

POLL_INTERVAL_SEC=10
POLL_TIMEOUT_SEC=300
```

`ENVIRONMENT_ID` and `BOT_ID` are visible in Copilot Studio under **Settings → Advanced → Details**.

### 4. Run

```bash
python evaluate.py
```

A browser opens on first run — sign in with your admin account. If you're already logged in via Azure CLI (`az login`), no browser is needed.

---

## Project Structure

```
evaluate.py       — entry point: loads config, orchestrates the run
src/
  auth.py         — Azure CLI token with MSAL interactive fallback
  client.py       — typed wrapper for the Power Platform REST API
  runner.py       — test set resolution, trigger, poll, result parsing
  reporter.py     — console output, JSON and JUnit XML writers
.env.template     — config template (copy to .env and fill in)
results/          — JSON + JUnit XML saved per run (git-ignored)
```

---

## API Request & Response Reference

### 1. Trigger an evaluation run

```
POST https://api.powerplatform.com/copilotstudio/environments/{environmentId}/bots/{botId}/api/makerevaluation/testsets/{testSetId}/run?api-version=2024-10-01
Authorization: Bearer <token>
Content-Type: application/json

{}
```

Response `202 Accepted`:
```json
{
  "runId": "dfee2b9e-d352-4f83-9599-55465e701fb9"
}
```

> The docs say this is a GET — it is a **POST**. GET returns 404.

---

### 2. Poll for results

```
GET https://api.powerplatform.com/copilotstudio/environments/{environmentId}/bots/{botId}/api/makerevaluation/testruns/{runId}?api-version=2024-10-01
Authorization: Bearer <token>
```

Keep polling until `state` is no longer `"Queued"` or `"Running"`. Terminal states: `Completed`, `Failed`, `Cancelled`, `Error`.

Response:
```json
{
  "id": "<run-id>",
  "state": "Completed",
  "startTime": "2026-04-29T09:54:19.0809989+00:00",
  "endTime": "2026-04-29T09:58:22.9508527+00:00",
  "totalTestCases": 20,
  "testCasesProcessed": 20,
  "testCasesResults": [
    {
      "testCaseId": "<test-case-id>",
      "state": "Completed",
      "metricsResults": [
        {
          "type": "CompareMeaning",
          "result": {
            "status": "Pass",
            "data": {
              "score": "100"
            },
            "aiResultReason": "The agent answer and the expected response mean the same thing.",
            "errorReason": null
          }
        },
        {
          "type": "GeneralQuality",
          "result": {
            "status": "Fail",
            "data": {
              "abstention": "Yes",
              "relevance": "NA",
              "completeness": "No"
            },
            "aiResultReason": null,
            "errorReason": null
          }
        }
      ]
    }
  ]
}
```

### Key fields to focus on

| Field | Where | What it means |
|---|---|---|
| `state` (run level) | root | Whether the run finished — `"Completed"` means it ran, **not** that it passed |
| `testCasesResults[]` | root | One entry per test case |
| `metricsResults[].type` | per test case | Metric name — e.g. `CompareMeaning`, `GeneralQuality` |
| `metricsResults[].result.status` | per metric | `"Pass"` or `"Fail"` — this is your actual pass/fail signal |
| `metricsResults[].result.aiResultReason` | per metric | Why the AI judge scored it that way — read this when debugging failures |
| `metricsResults[].result.data` | per metric | Metric-specific scores (e.g. `score`, `abstention`, `relevance`, `completeness`) |
| `metricsResults[].result.errorReason` | per metric | Set if the metric itself failed to evaluate (not the same as a failing test) |

> All eval fields (`status`, `aiResultReason`, `data`, `errorReason`) are nested inside `metric["result"]` — not directly on `metric`.

---

## Lessons Learned

These cost real debugging time — saving you the same.

### 1. The start_run endpoint is a POST, not a GET

The official docs say GET. It is a **POST**. Using GET returns a 404 with no helpful error.

```
POST https://api.powerplatform.com/copilotstudio/environments/{envId}/bots/{botId}/api/makerevaluation/testsets/{testSetId}/run?api-version=2024-10-01
```

### 2. `state == "Completed"` does not mean the test passed

The API uses `"Completed"` to mean *the test ran*, not *the test passed*. To get actual pass/fail, read `metric["result"]["status"]` for each metric — do not use the top-level `state` field.

### 3. Metric fields are nested inside `result`

`status`, `aiResultReason`, and `errorReason` live inside `metric["result"]`, not directly on `metric`. Accessing them from the wrong level gives you empty values silently.

### 4. ISO 8601 timestamps have many flavours

Duration calculation broke because `strptime` with a fixed format didn't handle timezone offsets like `2026-04-28T10:34:53.2735669+00:00`. Fix: use `datetime.fromisoformat()` — it handles all variants.

### 5. Read the AI failure reasons

When tests fail, the `aiResultReason` field tells you *why* the AI judge scored the response poorly. In testing, all 12 failures pointed to the same root cause: the agent gave suggestions instead of a "not found" response. One instruction added to the system prompt fixed it — pass rate jumped from ~20% to 80%+. Don't just look at scores; read the reasons.


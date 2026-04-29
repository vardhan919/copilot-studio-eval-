import subprocess
import json
import msal
from typing import Optional

_SCOPES = [
    "https://api.powerplatform.com/CopilotStudio.MakerOperations.Read",
    "https://api.powerplatform.com/CopilotStudio.MakerOperations.ReadWrite",
]
_AUTHORITY = "https://login.microsoftonline.com/{tenant_id}"

_token_cache = msal.SerializableTokenCache()


def get_token(tenant_id: str, client_id: Optional[str] = None) -> str:
    # 1. Try Azure CLI — works locally and in ADO pipelines with a service connection
    token = _try_azure_cli()
    if token:
        return token

    # 2. Fall back to interactive browser (first-time local dev only)
    return _get_token_interactive(tenant_id, client_id)


def _try_azure_cli() -> Optional[str]:
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token",
             "--resource", "https://api.powerplatform.com",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=15,
        )
        token = result.stdout.strip()
        if token:
            return token
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _get_token_interactive(tenant_id: str, client_id: Optional[str] = None) -> str:
    if not client_id:
        raise EnvironmentError("CLIENT_ID is not set. Add it to your .env file.")
    app = msal.PublicClientApplication(
        client_id,
        authority=_AUTHORITY.format(tenant_id=tenant_id),
        token_cache=_token_cache,
    )
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]

    print("A browser window will open — sign in and approve the permissions request.")
    result = app.acquire_token_interactive(scopes=_SCOPES)
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error_description', result.get('error'))}")
    return result["access_token"]

"""Print new private production secrets for app.local.toml.

Run this on the deployment host. The output contains secrets and must never
be committed, pasted into public tickets, or reused across environments.
"""

import base64
import secrets


def fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def main() -> None:
    print(f'auth_session_secret = "{secrets.token_urlsafe(48)}"')
    print(f'customer_access_token_encryption_key = "{fernet_key()}"')
    print(f'model_connection_secret_encryption_key = "{fernet_key()}"')
    print(f'lark_config_encryption_key = "{fernet_key()}"')


if __name__ == "__main__":
    main()

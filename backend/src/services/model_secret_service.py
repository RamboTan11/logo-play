"""Authenticated encryption boundary for stored provider API Keys."""

from typing import cast

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models import ModelConnectionSecret


class SecretConfigurationError(RuntimeError):
    """Raised when the private deployment encryption configuration is unusable."""


class ModelConnectionSecretService:
    """Encrypt and decrypt model connection keys without exposing ciphertext."""

    key_version = "v1"

    def __init__(self, raw_key: str | None) -> None:
        if not raw_key:
            raise SecretConfigurationError("Model connection secret encryption is not configured")
        try:
            self._cipher = Fernet(raw_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise SecretConfigurationError("Model connection secret encryption is invalid") from error

    async def replace(self, session: AsyncSession, connection_id: str, api_key: str) -> None:
        """Persist only authenticated encrypted key material for one connection."""

        secret = await session.get(ModelConnectionSecret, connection_id)
        ciphertext = self._cipher.encrypt(api_key.encode("utf-8")).decode("ascii")
        if secret is None:
            session.add(
                ModelConnectionSecret(
                    connection_id=connection_id,
                    encrypted_api_key=ciphertext,
                    encryption_key_version=self.key_version,
                )
            )
            return
        secret.encrypted_api_key = ciphertext
        secret.encryption_key_version = self.key_version

    async def read(self, session: AsyncSession, connection_id: str) -> str | None:
        """Decrypt a key for adapter use only; callers must never log or return it."""

        secret = await session.get(ModelConnectionSecret, connection_id)
        if secret is None:
            return None
        if secret.encryption_key_version != self.key_version:
            raise SecretConfigurationError("Model connection secret key version is unavailable")
        try:
            return cast(
                str,
                self._cipher.decrypt(secret.encrypted_api_key.encode("ascii")).decode("utf-8"),
            )
        except (InvalidToken, UnicodeDecodeError) as error:
            raise SecretConfigurationError("Stored model connection secret cannot be decrypted") from error

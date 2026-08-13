"""Authenticated encryption boundary for Lark routing values."""

from typing import cast

from cryptography.fernet import Fernet, InvalidToken


class LarkSecretConfigurationError(RuntimeError):
    """Raised when encrypted Lark configuration cannot be used safely."""


class LarkSecretService:
    """Encrypt and decrypt values without exposing ciphertext to API callers."""

    def __init__(self, raw_key: str | None) -> None:
        if not raw_key:
            raise LarkSecretConfigurationError("Lark encryption is not configured")
        try:
            self._cipher = Fernet(raw_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise LarkSecretConfigurationError("Lark encryption configuration is invalid") from error

    def encrypt(self, value: str) -> str:
        return cast(str, self._cipher.encrypt(value.encode("utf-8")).decode("ascii"))

    def decrypt(self, ciphertext: str) -> str:
        try:
            return cast(str, self._cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as error:
            raise LarkSecretConfigurationError("Stored Lark configuration cannot be decrypted") from error

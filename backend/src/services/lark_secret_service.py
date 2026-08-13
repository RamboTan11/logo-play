"""Authenticated encryption boundary for Lark routing values."""

from typing import cast

from cryptography.fernet import Fernet, InvalidToken


class LarkSecretConfigurationError(RuntimeError):
    """Raised when encrypted Lark configuration cannot be used safely."""


class LarkSecretService:
    """Encrypt and decrypt values without exposing ciphertext to API callers."""

    def __init__(self, raw_key: str | None) -> None:
        self._cipher: Fernet | None = None
        self._configuration_error: str | None = None
        if not raw_key:
            self._configuration_error = "Lark encryption is not configured"
            return
        try:
            self._cipher = Fernet(raw_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            self._configuration_error = "Lark encryption configuration is invalid"

    def _require_cipher(self) -> Fernet:
        if self._cipher is None:
            raise LarkSecretConfigurationError(
                self._configuration_error or "Lark encryption is unavailable"
            )
        return self._cipher

    @property
    def is_configured(self) -> bool:
        return self._cipher is not None

    def encrypt(self, value: str) -> str:
        return cast(str, self._require_cipher().encrypt(value.encode("utf-8")).decode("ascii"))

    def decrypt(self, ciphertext: str) -> str:
        try:
            return cast(str, self._require_cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as error:
            raise LarkSecretConfigurationError("Stored Lark configuration cannot be decrypted") from error

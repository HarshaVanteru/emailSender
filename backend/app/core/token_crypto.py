"""Encryption keys belong in server secrets, never in database rows or responses."""
from cryptography.fernet import Fernet

from app.core import config


def cipher() -> Fernet:
    if not config.TOKEN_ENCRYPTION_KEY:
        raise ValueError("TOKEN_ENCRYPTION_KEY must be configured")
    return Fernet(config.TOKEN_ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return cipher().decrypt(value.encode()).decode()

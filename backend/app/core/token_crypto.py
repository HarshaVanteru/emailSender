"""Encryption keys belong in server secrets, never in database rows or responses."""
from cryptography.fernet import Fernet, MultiFernet

from app.core import config


def cipher() -> MultiFernet:
    if not config.TOKEN_ENCRYPTION_KEY:
        raise ValueError("TOKEN_ENCRYPTION_KEY must be configured")
    keys = [config.TOKEN_ENCRYPTION_KEY, *filter(None, config.TOKEN_ENCRYPTION_PREVIOUS_KEYS.split(','))]
    return MultiFernet([Fernet(key.strip().encode()) for key in keys])


def encrypt(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def decrypt(value: str, ttl=None) -> str:
    return cipher().decrypt(value.encode(), ttl=ttl).decode()

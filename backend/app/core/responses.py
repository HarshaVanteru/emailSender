"""Shared response policy for private mailbox content."""
from fastapi import Response


def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"

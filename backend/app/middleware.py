"""
Request middleware: correlation IDs, browser security headers and safe errors.

Security headers are read from `vercel.json`, so the file Vercel applies in
production is also the single source for local development and tests (SEC-22).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import error_body

logger = logging.getLogger("backend")

CORRELATION_HEADER = "X-Request-ID"


def load_vercel_headers(vercel_json: Path) -> list[tuple[re.Pattern[str], list[tuple[str, str]]]]:
    """Parse the `headers` rules of vercel.json into (path regex, headers) pairs."""
    config = json.loads(vercel_json.read_text(encoding="utf-8"))
    rules = []
    for rule in config.get("headers", []):
        # vercel.json sources used here ("/(.*)", "/api/(.*)") are valid regular expressions
        pattern = re.compile(rule["source"])
        rules.append((pattern, [(h["key"], h["value"]) for h in rule["headers"]]))
    return rules


class SecurityMiddleware:
    """
    Pure ASGI middleware (it also wraps unhandled exceptions, which Starlette's
    BaseHTTPMiddleware cannot do reliably):

    * gives every request a correlation ID, returned in X-Request-ID;
    * adds the security headers from vercel.json to every response;
    * turns unhandled exceptions into a generic 500 JSON body. Details go to
      the server log with the correlation ID, never to the client (SEC-24).
    """

    def __init__(self, app: ASGIApp, header_rules):
        self.app = app
        self.header_rules = header_rules

    def _headers_for(self, path: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for pattern, rule_headers in self.header_rules:
            if pattern.fullmatch(path):
                headers.update(rule_headers)
        return headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = uuid.uuid4().hex
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        extra = {**self._headers_for(scope["path"]), CORRELATION_HEADER: correlation_id}
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                existing = {k.decode().lower() for k, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                for key, value in extra.items():
                    if key.lower() not in existing:
                        message["headers"].append((key.encode(), value.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("Unhandled error (correlation_id=%s)", correlation_id)
            if started:
                raise
            body = json.dumps(error_body(
                "internal_error",
                "Something went wrong on our side. Please try again or contact your administrator.",
                correlation_id,
            )).encode()
            await send_with_headers({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body})

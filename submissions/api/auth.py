"""Who is calling the API.

auth = "cognito" (AWS): the browser signs in through Cognito (federated to the company identity provider) and sends
the Cognito ID token as `Authorization: Bearer <token>`. API Gateway's JWT authorizer verifies the signature, issuer,
audience and expiry on every route before this function runs, and the API has no other way in, so the token here is
already verified: its claims are only read. The signed-in e-mail must belong to an active app_user (who may use the
app, and who is an administrator).

auth = "none" (local development and tests): no sign-in; a fronting proxy may pass X-Forwarded-User.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from flask import abort, current_app, g, request

from submissions.ops import audit
from submissions.users import UserRepository


@dataclass(frozen=True)
class Identity:
    username: str                # recorded on requests, exceptions and the audit trail
    display_name: str
    email: str | None
    is_admin: bool


def current_user() -> str:
    return g.identity.username


def _claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        abort(401, "Sign in again (the session token is not readable)")


def identify(auth_mode: str, client_id: str | None) -> Identity:
    """The caller's identity, or abort 401 (no / wrong token) or 403 (not an app user)."""
    if auth_mode == "none":
        name = (request.headers.get("X-Forwarded-User") or "internal-user")[:100]
        return Identity(name, name, None, True)
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        abort(401, "Sign in first")
    claims = _claims(header[7:].strip())
    if claims.get("token_use") != "id" or (client_id and claims.get("aud") != client_id):
        abort(401, "Sign in again (unexpected token)")
    email = (claims.get("email") or "").strip().lower()
    engine = current_app.extensions["submissions"].engine
    user = UserRepository(engine).find_by_email(email)
    if user is None or not user.is_active:
        audit.record(engine, email or claims.get("sub", "-"), "LOGIN_DENIED", target=email or None,
                     reason="disabled" if user else "not registered", ip=request.remote_addr)
        abort(403, f"{email or 'This account'} is not registered for Bureau Submissions, or is disabled. "
                   "Ask an administrator to add you.")
    return Identity(user.username, user.display_name, user.email, user.is_admin)

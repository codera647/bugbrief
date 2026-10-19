import asyncio
from dataclasses import dataclass
from ipaddress import ip_address

import jwt
from fastapi import Request
from jwt import PyJWKClient

from .domain import Role, uuid_string
from .errors import AppError

DEMO_USER = "00000000-0000-4000-8000-000000000001"
DEMO_WORKSPACE = "00000000-0000-4000-8000-000000000010"


@dataclass(frozen=True)
class Identity:
    user_id: str


@dataclass(frozen=True)
class Membership:
    user_id: str
    workspace_id: str
    role: Role
    name: str

    def require_edit(self):
        if self.role == "viewer":
            raise AppError(403, "role_denied", "You have read-only access to this workspace.")


class Authenticator:
    def __init__(self, settings):
        self.settings = settings
        self.keys = PyJWKClient(settings.supabase_url + "/auth/v1/.well-known/jwks.json", lifespan=300, timeout=10) if settings.mode == "production" else None

    async def identify(self, request: Request) -> Identity:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or len(authorization) > 8192:
            raise AppError(401, "invalid_session", "Sign in to continue.")
        token = authorization[7:]
        if self.settings.mode == "demo":
            try:
                local = request.client is not None and ip_address(request.client.host).is_loopback
            except ValueError:
                local = False
            if not local or token != "local-demo":
                raise AppError(401, "invalid_session", "Local demo access is available only on this computer.")
            return Identity(DEMO_USER)
        try:
            key = await asyncio.to_thread(self.keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience="authenticated", issuer=self.settings.supabase_url + "/auth/v1", options={"require": ["exp", "iat", "sub", "aud", "iss"]})
            return Identity(uuid_string(claims["sub"]))
        except (jwt.PyJWTError, ValueError, KeyError):
            raise AppError(401, "invalid_session", "Your session expired. Sign in to continue.") from None

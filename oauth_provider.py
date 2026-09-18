"""OAuthAuthorizationServerProvider backing this MCP server's remote OAuth
2.1 login. Every method here is a thin httpx call to the Yabot Jobs
backend's /oauth/* endpoints (app/api/routes/oauth.py in yabot.jobs-backend)
— this server holds no OAuth state of its own, matching its existing
"never touches the DB directly" design.

The PKCE verifier check and authorization-code expiry/redirect_uri checks
are done by the mcp SDK itself (in mcp.server.auth.handlers.token) before
exchange_authorization_code is ever called — this provider only needs to
supply accurate data for load_authorization_code/load_refresh_token to
build on.
"""

import os
from typing import Any
from urllib.parse import urlencode

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

API_BASE_URL = os.environ.get("YABOT_API_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_BASE_URL = os.environ.get("YABOT_FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


async def _api_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0) as client:
        return await client.request(method, path, **kwargs)


def _split_scopes(scopes: str | None) -> list[str]:
    return scopes.split() if scopes else []


class YabotOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        response = await _api_request("GET", f"/oauth/clients/{client_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return OAuthClientInformationFull(
            client_id=data["client_id"],
            client_name=data["client_name"],
            redirect_uris=data["redirect_uris"],
            # No client secret is ever stored/checked server-side — every
            # MCP client is treated as public, authenticated by PKCE alone.
            token_endpoint_auth_method="none",
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        response = await _api_request(
            "POST",
            "/oauth/clients",
            json={
                "client_id": client_info.client_id,
                "client_name": client_info.client_name or "MCP client",
                "redirect_uris": [str(uri) for uri in (client_info.redirect_uris or [])],
            },
        )
        response.raise_for_status()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        response = await _api_request(
            "POST",
            "/oauth/authorizations",
            json={
                "client_id": client.client_id,
                "redirect_uri": str(params.redirect_uri),
                "code_challenge": params.code_challenge,
                "code_challenge_method": "S256",
                "scopes": " ".join(params.scopes) if params.scopes else None,
                "resource": params.resource,
                "state": params.state,
            },
        )
        response.raise_for_status()
        request_id = response.json()["request_id"]
        return f"{FRONTEND_BASE_URL}/oauth/authorize?{urlencode({'request_id': request_id})}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        response = await _api_request("GET", f"/oauth/authorization-codes/{authorization_code}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return AuthorizationCode(
            code=authorization_code,
            scopes=_split_scopes(data["scopes"]),
            expires_at=_iso_to_timestamp(data["expires_at"]),
            client_id=data["client_id"],
            code_challenge=data["code_challenge"],
            redirect_uri=data["redirect_uri"],
            redirect_uri_provided_explicitly=True,
            resource=data["resource"],
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        response = await _api_request(
            "POST",
            f"/oauth/authorization-codes/{authorization_code.code}/exchange",
            json={"client_id": client.client_id},
        )
        if response.status_code == 400:
            raise TokenError(error="invalid_grant", error_description=response.json().get("detail"))
        response.raise_for_status()
        data = response.json()
        return OAuthToken(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data["expires_in"],
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        response = await _api_request("GET", f"/oauth/refresh-tokens/{refresh_token}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        return RefreshToken(
            token=refresh_token,
            client_id=data["client_id"],
            scopes=[],
            expires_at=int(_iso_to_timestamp(data["expires_at"])),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        response = await _api_request(
            "POST",
            f"/oauth/refresh-tokens/{refresh_token.token}/exchange",
            json={"client_id": client.client_id},
        )
        if response.status_code == 400:
            raise TokenError(error="invalid_grant", error_description=response.json().get("detail"))
        response.raise_for_status()
        data = response.json()
        return OAuthToken(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data["expires_in"],
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        # No dedicated introspection endpoint needed — this reuses the same
        # dual-mode auth (GET /auth/me) every other tool call goes through,
        # since the "access token" a client holds is just a PersonalAccessToken.
        response = await _api_request("GET", "/auth/me", headers={"Authorization": f"Bearer {token}"})
        if response.status_code != 200:
            return None
        user = response.json()
        return AccessToken(token=token, client_id="", scopes=[], subject=user["id"])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_type_hint = "refresh_token" if isinstance(token, RefreshToken) else "access_token"
        response = await _api_request(
            "POST", "/oauth/tokens/revoke", json={"token": token.token, "token_type_hint": token_type_hint}
        )
        response.raise_for_status()


def _iso_to_timestamp(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value).timestamp()

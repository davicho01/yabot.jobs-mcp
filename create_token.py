"""One-off CLI to mint a personal access token for the MCP server, without
needing the frontend. Drives the same magic-link login flow the web app
uses, then calls POST /auth/tokens with the resulting session cookie.

Usage:
    python -m mcp_server.create_token --email you@example.com --label "Claude Desktop"

The magic link is emailed (see app.services.email) — in local dev without
real email configured, check the backend's logs/console for the link
instead. Paste just the `token` query-param value from that link when
prompted.
"""

import argparse
import sys

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Your Yabot Jobs account email.")
    parser.add_argument("--label", default="MCP server", help="Label for the new token (default: 'MCP server').")
    parser.add_argument(
        "--expires-in-days", type=int, default=None, help="Optional expiry; omit for a token that never expires."
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="Backend base URL (default: http://localhost:8000)."
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0) as client:
        response = client.post("/auth/request-link", json={"email": args.email})
        response.raise_for_status()
        print(f"Magic link sent to {args.email}. Check your email (or the backend's logs in local dev).")

        magic_link_token = input("Paste the 'token' value from the magic link URL: ").strip()
        response = client.post("/auth/verify", json={"token": magic_link_token})
        if response.status_code >= 400:
            print(f"Login failed ({response.status_code}): {response.text}", file=sys.stderr)
            raise SystemExit(1)

        response = client.post(
            "/auth/tokens", json={"label": args.label, "expires_in_days": args.expires_in_days}
        )
        response.raise_for_status()
        token = response.json()["token"]

    print("\nPersonal access token created — save it now, it won't be shown again:\n")
    print(f"  {token}\n")
    print("Set it as YABOT_ACCESS_TOKEN in the MCP server's environment (see mcp_server/README.md).")


if __name__ == "__main__":
    main()

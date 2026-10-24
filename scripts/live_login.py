"""Log in to Navimow with the integration's OAuth flow and save tokens for live tests.

Starts a local HTTP server that receives the OAuth redirect, prints the login
URL, exchanges the code with the same code used by the config flow and writes
the tokens to .navimow_live/tokens.json (git-ignored).

Usage, from the repository root:
    python scripts/live_login.py [--port 8765] [--timeout 600]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.navimow.api import (  # noqa: E402
    NavimowError,
    async_exchange_code,
    build_authorize_url,
    token_data_to_entry_data,
)
from custom_components.navimow.const import CALLBACK_PATH  # noqa: E402

LIVE_DIR = ROOT / ".navimow_live"
TOKEN_FILE = LIVE_DIR / "tokens.json"


async def main(args: argparse.Namespace) -> int:
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{args.port}{CALLBACK_PATH}"
    received: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()

    async def handle_callback(request: web.Request) -> web.Response:
        if not received.done():
            received.set_result(dict(request.query))
        return web.Response(text="Navimow login received: you can close this window.")

    app = web.Application()
    app.router.add_get(CALLBACK_PATH, handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()

    print("Open this URL in the browser and log in:\n", flush=True)
    print(build_authorize_url(redirect_uri, state), "\n", flush=True)

    try:
        query = await asyncio.wait_for(received, args.timeout)
    except TimeoutError:
        print("No redirect received before the timeout.")
        return 1
    finally:
        await runner.cleanup()

    print(f"Redirect received with parameters: {sorted(query)}")
    if "state" not in query:
        print("- state: NOT echoed back by the login page")
    elif query["state"] == state:
        print("- state: echoed back correctly")
    else:
        print("- state: echoed back but DIFFERENT from the one sent")
    if "code" not in query:
        print("No authorization code in the redirect, aborting.")
        return 1

    async with ClientSession() as session:
        try:
            token_data = await async_exchange_code(session, query["code"], redirect_uri)
        except NavimowError as err:
            print(f"Code exchange failed: {err}")
            return 1

    print(f"Token response fields: {sorted(token_data)}")
    print(f"- expires_in: {token_data.get('expires_in')}")
    LIVE_DIR.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token_data_to_entry_data(token_data), indent=2))
    TOKEN_FILE.chmod(0o600)
    print(f"Tokens saved to {TOKEN_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=int, default=600, help="seconds to wait for login")
    sys.exit(asyncio.run(main(parser.parse_args())))

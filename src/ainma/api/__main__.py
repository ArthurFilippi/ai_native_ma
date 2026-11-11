"""Serve the API: `python -m ainma.api [--host H] [--port P]`. Uses the configured store."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

import uvicorn

from ainma.api.app import create_app
from ainma.runtime import open_runtime

log = logging.getLogger(__name__)


async def serve(host: str, port: int) -> None:
    runtime = await open_runtime()
    try:
        config = uvicorn.Config(create_app(runtime), host=host, port=port, log_level="info")
        await uvicorn.Server(config).serve()
    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the AI-native M&A API (DEMO_AUTH).")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()

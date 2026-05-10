"""Compatibility entrypoint for running the FastAPI app."""

from __future__ import annotations

import os

import uvicorn

from edd_agent.api.app import create_app


app = create_app()


def main() -> None:
    port = int(os.environ.get("PORT", "5050"))
    uvicorn.run("edd_agent.web:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()

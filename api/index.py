"""Vercel serverless entry point — wraps the FastAPI app for deployment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import app  # noqa: E402

handler = app

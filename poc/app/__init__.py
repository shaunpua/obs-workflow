"""Revenue observability POC.

Loads poc/.env (if present) so you never have to `source` it. Real environment
variables always win over the file, which is how the tests and hosts override it.
"""
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # python-dotenv not installed: fall back to the plain environment
    pass

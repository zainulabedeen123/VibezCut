"""Entry point for the FilmCraft Studio MCP server (stdio)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from studio.server import main  # noqa: E402

if __name__ == "__main__":
    main()

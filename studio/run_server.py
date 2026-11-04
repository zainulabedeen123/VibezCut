"""Entry point for the FilmCraft Studio MCP server (stdio)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Inside VibezCut.app (macOS) the studio is part of the signed bundle: writing __pycache__ there
# would break the signature (and /Applications may not be writable).
if ".app" + os.sep + "Contents" + os.sep in HERE + os.sep:
    sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from studio.server import main  # noqa: E402

if __name__ == "__main__":
    main()

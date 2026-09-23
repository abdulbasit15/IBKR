import sys

from .cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl+C: exit quietly with the conventional 130 (no traceback).
        print("\nStopped.")
        sys.exit(130)

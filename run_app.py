"""Entry point for frozen (PyInstaller) builds.

The package uses relative imports, so PyInstaller needs a plain script that
imports the package rather than running src/app.py directly.
"""
from src.app import main

if __name__ == "__main__":
    main()

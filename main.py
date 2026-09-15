"""RubyHost / Pterodactyl entrypoint. Set APP PY FILE to main.py (project root).

Do not point APP PY FILE at app/__main__.py — that breaks `import app`.
"""

from app.__main__ import main

if __name__ == "__main__":
    main()

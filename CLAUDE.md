See [AGENTS.md](AGENTS.md) for how to use these tools and the safety rules.

Development: `pip install -e .[dev]`, then `python -m pytest`. Tests build a fake KSP install in a
temp dir (`tests/conftest.py`); they never touch the real game.

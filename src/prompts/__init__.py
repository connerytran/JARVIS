from pathlib import Path

_DIR = Path(__file__).parent

def load(name: str) -> str:
    return (_DIR / f"{name}.txt").read_text()

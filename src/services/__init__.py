
import importlib
from pathlib import Path

TOOLS = []
for _file in Path(__file__).parent.glob("*.py"):
    if _file.stem.startswith("_"):
        continue
    _module = importlib.import_module(f"services.{_file.stem}")
    if hasattr(_module, "TOOLS"):
        TOOLS.extend(_module.TOOLS)

TOOL_MAP = {f.__name__: f for f in TOOLS}
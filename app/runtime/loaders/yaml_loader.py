"""
YAML loader helper for reading architecture files.
Uses PyYAML if installed, otherwise a robust lightweight fallback parser.
"""

import re
from typing import Dict, Any, List

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


def parse_yaml_string(content: str) -> Dict[str, Any]:
    """Parse YAML string using PyYAML or standard fallback."""
    if _YAML_AVAILABLE:
        try:
            return yaml.safe_load(content) or {}
        except Exception:
            pass

    # Lightweight fallback parser for our architecture YAML schemas
    result: Dict[str, Any] = {}
    lines = content.splitlines()
    current_key = None
    current_list: List[Any] = []
    in_list = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("- "):
            val = line[2:].strip().strip('"').strip("'")
            if current_key and isinstance(result.get(current_key), list):
                result[current_key].append(val)
            continue

        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val_str = parts[1].strip()

            if not val_str:
                current_key = key
                result[key] = []
                continue

            if val_str.startswith("[") and val_str.endswith("]"):
                inner = val_str[1:-1].strip()
                if not inner:
                    items = []
                else:
                    items = [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
                result[key] = items
                current_key = None
                continue

            if val_str.lower() == "true":
                result[key] = True
            elif val_str.lower() == "false":
                result[key] = False
            elif val_str.isdigit():
                result[key] = int(val_str)
            else:
                result[key] = val_str.strip('"').strip("'")
            current_key = key

    return result

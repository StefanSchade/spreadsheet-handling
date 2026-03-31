from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any


def flatten_json(obj: Any, parent: str | None = None, sep: str = ".") -> OrderedDict[str, str]:
    out = OrderedDict()
    if isinstance(obj, dict):
        for k, v in obj.items():  # bewahrt JSON-Key-Order
            key = k if parent is None else f"{parent}{sep}{k}"
            out.update(flatten_json(v, key, sep))
    elif isinstance(obj, list):
        # MVP: Liste als JSON-String im Parent
        out[parent] = json.dumps(obj, ensure_ascii=False)
    else:
        out[parent] = obj
    return out

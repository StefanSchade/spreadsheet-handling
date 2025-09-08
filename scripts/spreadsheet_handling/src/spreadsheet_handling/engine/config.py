# spreadsheet_handling/engine/config.py
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass(frozen=True)
class EngineConfig:
    levels: int = 3
    backend: str = "xlsx"              # "xlsx" | "csv"
    id_field: str = "id"
    label_field: str = "name"
    helper_prefix: str = "_"
    detect_fk: bool = True
    validate: Dict[str, str] = field(default_factory=dict)  # {"missing_fk": "...", "duplicate_ids": "..."}

    @staticmethod
    def from_dict(d: Dict) -> "EngineConfig":
        v = d.get("validate") or {}
        return EngineConfig(
            levels=int(d.get("levels", 3)),
            backend=str(d.get("backend", "xlsx")).lower(),
            id_field=str(d.get("id_field", "id")),
            label_field=str(d.get("label_field", "name")),
            helper_prefix=str(d.get("helper_prefix", "_")),
            detect_fk=bool(d.get("detect_fk", True)),
            validate={"missing_fk": v.get("missing_fk", "warn"),
                      "duplicate_ids": v.get("duplicate_ids", "warn")},
        )

@dataclass(frozen=True)
class SheetMeta:
    sheet_name: str
    id_field: str
    label_field: str


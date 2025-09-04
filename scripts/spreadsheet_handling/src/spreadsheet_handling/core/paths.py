# core/paths.py
def join_path(parts: list[str]) -> str:
    return ".".join(p for p in parts if p not in ("", None))


def split_path(p: str) -> list[str]:
    return p.split(".")

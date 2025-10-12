def add_validations(frames, *, rules: list[dict]):
    # get or create meta on either frames.meta (attr) or frames["_meta"] (dict key)
    if hasattr(frames, "meta"):
        meta = frames.meta or {}
        where = "attr"
    elif isinstance(frames, dict):
        meta = frames.get("_meta") or {}
        frames["_meta"] = meta
        where = "key"
    else:
        # last resort: create a temporary sidecar
        meta = {}
        where = "temp"

    constraints = list(meta.get("constraints") or [])
    for r in rules:
        rule = (r.get("rule") or {})
        if rule.get("type") != "in_list":
            raise ValueError(f"unsupported rule.type={rule.get('type')}")
        constraints.append({
            "sheet": r["sheet"],
            "column": r.get("column"),
            "rule": {"type": "in_list", "values": list(rule.get("values") or [])},
            "on_violation": r.get("on_violation", "error"),
        })

    meta["constraints"] = constraints

    if where == "attr":
        frames.meta = meta
    elif where == "key":
        frames["_meta"] = meta

    return frames

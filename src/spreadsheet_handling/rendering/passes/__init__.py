from . import meta_pass, validation_pass, style_pass

def apply_all(ir, meta):
    # deterministic order
    for mod in (meta_pass, validation_pass, style_pass):
        mod.apply(ir, meta)
    return ir

def test_add_validations_on_plain_dict():
    from spreadsheet_handling.domain.validations.validate_columns import add_validations
    frames = {"fees": __import__("pandas").DataFrame({"fee_type": []})}  # plain dict
    add_validations(frames, rules=[{
        "sheet": "fees",
        "column": "fee_type",
        "rule": {"type": "in_list", "values": ["origination", "service"]},
    }])
    assert "_meta" in frames
    assert frames["_meta"]["constraints"][0]["rule"]["values"] == ["origination", "service"]

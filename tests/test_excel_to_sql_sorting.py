from data_ingestion.excel_to_sql.sql_sorting import normalize_sql_sort_specs, sql_order_by_clause


def test_normalize_sql_sort_specs_preserves_priority_and_adds_tiebreaker():
    specs = normalize_sql_sort_specs(
        ["ColumnA:asc", "ColumnB:desc"],
        allowed_expressions={"ColumnA": "[ColumnA]", "ColumnB": "[ColumnB]", "hash_value": "[hash_value]"},
        default=[("hash_value", "asc")],
    )

    assert [item.field for item in specs] == ["ColumnA", "ColumnB", "hash_value"]
    assert sql_order_by_clause(specs) == "[ColumnA] ASC, [ColumnB] DESC, [hash_value] ASC"


def test_normalize_sql_sort_specs_rejects_unknown_field_and_direction():
    try:
        normalize_sql_sort_specs(["evil:asc"], allowed_expressions={"safe": "[safe]"}, default=[("safe", "asc")])
    except ValueError as exc:
        assert "不支援的排序欄位" in str(exc)
    else:
        raise AssertionError("unknown field should fail")

    try:
        normalize_sql_sort_specs(["safe:sideways"], allowed_expressions={"safe": "[safe]"}, default=[("safe", "asc")])
    except ValueError as exc:
        assert "排序方向只允許" in str(exc)
    else:
        raise AssertionError("bad direction should fail")

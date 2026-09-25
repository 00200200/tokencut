from __future__ import annotations

import json

from usagetrim.core.cache import ContextCache
from usagetrim.core.table import compact_table


def test_compact_table_json_toon():
    # 50 rows of structured records with repetitive keys
    records = [
        {
            "id": i,
            "username": f"user_{i}",
            "email": f"user_{i}@company.internal",
            "role": "engineer" if i % 2 == 0 else "manager",
            "active": True,
        }
        for i in range(50)
    ]
    raw = json.dumps(records)
    res = compact_table(raw, budget=2000, format_type="toon")
    assert res.row_count == 50
    assert res.column_count == 5
    assert "[id | username | email | role | active]" in res.text
    assert "user_0 | user_0@company.internal" in res.text
    # Should save significant tokens (>40%) by omitting repeated keys
    assert res.reduction_pct > 35.0
    assert res.compacted_tokens < res.original_tokens
    # Verify CCR
    assert ContextCache().retrieve(res.ref_id) == raw


def test_compact_table_markdown_format():
    records = [{"name": "Alpha", "val": 10}, {"name": "Beta", "val": 20}]
    raw = json.dumps(records)
    res = compact_table(raw, budget=1000, format_type="markdown")
    assert "| name | val |" in res.text
    assert "| --- | --- |" in res.text
    assert "| Alpha | 10 |" in res.text


def test_compact_table_csv_input():
    csv_text = "id,name,department\n1,Alice,Engineering\n2,Bob,Product\n3,Charlie,Design\n"
    res = compact_table(csv_text, budget=1000, format_type="toon")
    assert res.row_count == 3
    assert res.column_count == 3
    assert "[id | name | department]" in res.text
    assert "1 | Alice | Engineering" in res.text


def test_compact_table_budget_truncation():
    records = [{"id": i, "data": "payload " * 20} for i in range(100)]
    raw = json.dumps(records)
    res = compact_table(raw, budget=300, format_type="toon")
    assert res.compacted_tokens <= 350
    assert "rows omitted to fit token budget" in res.text
    assert res.ref_id is not None
    # Verify original recovered
    recovered = ContextCache().retrieve(res.ref_id)
    assert len(json.loads(recovered)) == 100


def test_compact_table_secret_scrubbing():
    secret = "ghp_" + "C" * 36
    records = [{"id": 1, "token": secret}]
    raw = json.dumps(records)
    res = compact_table(raw, budget=1000)
    assert secret not in res.text
    assert "[REDACTED" in res.text

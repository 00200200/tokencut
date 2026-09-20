from __future__ import annotations

import json

from tokencut.core.json_slimmer import slim_json, slim_json_data


def test_slim_json_data_array():
    data = {"users": [{"id": i, "name": f"User {i}"} for i in range(50)]}
    slimmed = slim_json_data(data, max_array_items=2)
    assert len(slimmed["users"]) == 3  # 2 items + 1 omitted notice
    assert "omitted by tokencut" in slimmed["users"][2]


def test_slim_json_data_long_string():
    data = {"payload": "A" * 500}
    slimmed = slim_json_data(data, max_string_len=50)
    assert len(slimmed["payload"]) < 100
    assert "chars omitted" in slimmed["payload"]


def test_slim_json_text_compaction():
    raw = json.dumps([{"id": i, "title": f"Task {i}"} for i in range(100)])
    result = slim_json(raw, max_array_items=3)
    assert "Task 0" in result
    assert "Task 1" in result
    assert "Task 2" in result
    assert "omitted by tokencut" in result
    # CCR cache tag should be injected if substantial reduction
    assert "Ref: tc_" in result


def test_slim_json_invalid_fallback():
    invalid = "not json at all"
    assert slim_json(invalid) == invalid

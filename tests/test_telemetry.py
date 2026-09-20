from tokencut.core.telemetry import TelemetryStore


def test_telemetry_store(tmp_path):
    db = tmp_path / "telemetry_test.db"
    store = TelemetryStore(db_path=db)

    # Initial stats
    s0 = store.get_stats()
    assert s0.total_runs == 0
    assert s0.saved_avg == 0

    # Record event
    store.record(
        raw_claude=1000,
        compact_claude=200,
        raw_openai=900,
        compact_openai=180,
        raw_gemini=950,
        compact_gemini=190,
    )

    s1 = store.get_stats()
    assert s1.total_runs == 1
    assert s1.saved_claude == 800
    assert s1.saved_openai == 720
    assert s1.saved_gemini == 760
    assert s1.reduction_pct > 70.0
    assert s1.estimated_usd_saved > 0

    # Clear
    store.clear()
    assert store.get_stats().total_runs == 0

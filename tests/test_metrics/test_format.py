"""Tests for Prometheus-format serialization."""
from src.metrics.prometheus_format import to_prometheus_text


def test_counter_inc():
    from src.metrics.counter import Counter
    c = Counter("hits", "Hits", label_names=["path"])
    c.inc(amount=1, path="/a")
    c.inc(amount=2, path="/a")
    assert c.get(path="/a") == 3


def test_gauge_set_and_inc():
    from src.metrics.gauge import Gauge
    g = Gauge("inflight", "Inflight reqs", label_names=["server"])
    g.set(5, server="web")
    g.inc(amount=1, server="web")
    assert g.get(server="web") == 6


def test_histogram_observe():
    from src.metrics.histogram import Histogram
    h = Histogram("dur", "Duration", label_names=["op"], buckets=(1.0, 2.0, float("inf")))
    h.observe(0.5, op="x")
    h.observe(1.5, op="x")
    h.observe(3.0, op="x")
    assert h._totals[("x",)] == 3
    assert h._sums[("x",)] == 5.0


def test_to_prometheus_text_counter():
    from src.metrics.counter import Counter
    c = Counter("pageviews_total", "Page views", label_names=["path"])
    c.inc(amount=7, path="/home")
    text = to_prometheus_text([c])
    assert "# HELP pageviews_total" in text
    assert "# TYPE pageviews_total counter" in text
    assert 'pageviews_total{path="/home"} 7' in text
    assert text.endswith("\n")


def test_labels_omitted_when_empty():
    from src.metrics.counter import Counter
    c = Counter("naked_total", "No labels")
    c.inc(amount=3)
    text = to_prometheus_text([c])
    # No label braces when labels are empty
    assert "naked_total 3\n" in text


def test_ingest_duration_histogram_buckets():
    """D2: INGEST_DURATION_SECONDS uses correct buckets (30,60,90,120,180,300,600,inf)."""
    from src.metrics import INGEST_DURATION_SECONDS
    from src.metrics.histogram import Histogram
    assert isinstance(INGEST_DURATION_SECONDS, Histogram)
    assert INGEST_DURATION_SECONDS.name == "ruflo_ingest_duration_seconds"
    assert INGEST_DURATION_SECONDS.label_names == ["verdict"]
    expected = (30, 60, 90, 120, 180, 300, 600, float("inf"))
    assert INGEST_DURATION_SECONDS.buckets == expected, (
        f"buckets={INGEST_DURATION_SECONDS.buckets}, expected={expected}"
    )


def test_ingest_duration_seconds_observe():
    """D2: histogram observe() distributes across buckets correctly."""
    from src.metrics.histogram import Histogram
    h = Histogram("test_dur", "Test", label_names=["verdict"],
                  buckets=(30, 60, 90, 120, 180, 300, 600, float("inf")))
    h.observe(45.0, verdict="success")   # falls in 60 bucket
    h.observe(150.0, verdict="success")  # falls in 180 bucket
    h.observe(700.0, verdict="failed")   # falls in +Inf bucket

    key_ok = ("success",)
    assert h._totals[key_ok] == 2
    assert h._sums[key_ok] == 195.0
    counts_ok = h._counts[key_ok]
    assert counts_ok.get(30, 0) == 0
    assert counts_ok.get(60, 0) == 1
    assert counts_ok.get(90, 0) == 1
    assert counts_ok.get(120, 0) == 1
    assert counts_ok.get(180, 0) == 2
    assert counts_ok.get(300, 0) == 2
    assert counts_ok.get(600, 0) == 2
    assert counts_ok.get(float("inf"), 0) == 2

    key_fail = ("failed",)
    assert h._totals[key_fail] == 1
    assert h._sums[key_fail] == 700.0


def test_ingest_verdict_counter_increments():
    """D2: INGEST_VERDICT_TOTAL counter increments with verdict + reason labels."""
    from src.metrics.counter import Counter
    c = Counter("test_verdict", "Test", label_names=["verdict", "reason"])
    c.inc(verdict="success", reason="")
    c.inc(verdict="failed", reason="api_error")
    c.inc(verdict="rejected", reason="low_confidence")
    c.inc(verdict="failed", reason="api_error")
    c.inc(verdict="rejected", reason="evidence_ref")

    assert c.get(verdict="success", reason="") == 1
    assert c.get(verdict="failed", reason="api_error") == 2
    assert c.get(verdict="rejected", reason="low_confidence") == 1
    assert c.get(verdict="rejected", reason="evidence_ref") == 1


def test_ingest_verdict_total_is_registered():
    """D2: INGEST_VERDICT_TOTAL is a registered Counter with correct labels."""
    from src.metrics import INGEST_VERDICT_TOTAL
    from src.metrics.counter import Counter
    assert isinstance(INGEST_VERDICT_TOTAL, Counter)
    assert INGEST_VERDICT_TOTAL.name == "ruflo_ingest_verdict_total"
    assert INGEST_VERDICT_TOTAL.label_names == ["verdict", "reason"]


def test_to_prometheus_text_histogram_buckets():
    from src.metrics.histogram import Histogram
    h = Histogram("lat", "Latency", buckets=(1.0, 2.0, float("inf")))
    h.observe(0.5)
    h.observe(1.5)
    text = to_prometheus_text([h])
    assert "# TYPE lat histogram" in text
    assert 'lat_bucket{le="1.0"} 1' in text
    assert 'lat_bucket{le="2.0"} 2' in text
    assert 'lat_bucket{le="+Inf"} 2' in text
    assert "lat_sum 2.0" in text
    assert "lat_count 2" in text

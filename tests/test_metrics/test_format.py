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

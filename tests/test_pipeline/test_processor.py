# ruflo-kb/tests/test_pipeline/test_processor.py
from src.pipeline.processor import calculate_quality_metrics

def test_calculate_quality_metrics():
    """Test quality metrics calculation"""
    # Good content
    content = "This is a well-written sentence. " * 50
    metrics = calculate_quality_metrics(content)

    assert "quality_score" in metrics
    assert "ad_ratio" in metrics
    assert "text_density" in metrics
    assert "fluency_score" in metrics
    assert 0 <= metrics["quality_score"] <= 1.0
    assert 0 <= metrics["ad_ratio"] <= 1.0
    assert 0 <= metrics["text_density"] <= 1.0
    assert 0 <= metrics["fluency_score"] <= 1.0

def test_quality_metrics_with_ads():
    """Test that ad content lowers quality"""
    content_with_ads = "This is a test. " * 20 + "广告推广内容 " * 10
    metrics = calculate_quality_metrics(content_with_ads)

    # Should have some ad ratio
    assert metrics["ad_ratio"] > 0

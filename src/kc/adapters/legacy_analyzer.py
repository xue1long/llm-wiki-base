"""Compatibility seam for analyzer output; validation stays local."""

from src.kc.compiler.extract import parse_candidate_json


class LegacyAnalyzer:
    def parse(self, payload: str) -> dict:
        return parse_candidate_json(payload)

"""Quality gate CLI subcommands."""
import argparse
import json
import sys
from pathlib import Path

from ..services.quality import run_quality_judge
from ..quality.types import QualitySettings
from ..lib.write_hooks import safe_write


def cmd_quality_score(args: argparse.Namespace) -> None:
    """Score a single markdown file via LLM judge (no wiki types dependency)."""
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(2)
    page_body = path.read_text(encoding="utf-8")
    page_id = path.stem
    page_type = _guess_page_type(path)
    settings = _load_settings(path.parent)
    judgment_dict = run_quality_judge(page_id, page_type, page_body, settings)
    print(json.dumps(judgment_dict, indent=2, ensure_ascii=False))


def cmd_quality_config_show(_args: argparse.Namespace) -> None:
    """Print current QualitySettings (per-project or default)."""
    settings = _load_settings(Path.cwd())
    print(f"mode: {settings.mode}")
    print(f"is_active: {settings.is_active()}")
    print(f"sample_rate: {settings.sample_rate}")
    print(f"threshold_pass: {settings.threshold_pass}")
    print(f"max_retries: {settings.max_retries}")
    print(f"weights: {json.dumps(settings.weights, indent=2, ensure_ascii=False)}")


def cmd_quality_config_set(args: argparse.Namespace) -> None:
    """Set a config key (supports nested `weights.factuality`)."""
    config_path = _config_path(args.config_root or Path.cwd())
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        data = {}
    # Try numeric, then fall back to string / bool.
    raw = args.value
    if raw.lower() in ("true", "false"):
        v: object = raw.lower() == "true"
    else:
        try:
            v = int(raw)
        except ValueError:
            try:
                v = float(raw)
            except ValueError:
                v = raw
    if "." in args.key:
        top, sub = args.key.split(".", 1)
        data.setdefault(top, {})[sub] = v
    else:
        data[args.key] = v
    safe_write(config_path, json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Set {args.key} = {v}")


def _guess_page_type(path: Path) -> str:
    # Light heuristic: derive from the parent dir name.
    parent = path.parent.name
    if parent in ("sources", "entities", "concepts", "synthesis"):
        return "entity" if parent == "entities" else parent.rstrip("s")
    return "entity"


def _load_settings(project_root: Path) -> QualitySettings:
    """Load QualitySettings from per-project JSON or fall back to defaults."""
    cfg = _config_path(project_root)
    if not cfg.exists():
        return QualitySettings()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    return QualitySettings(
        mode=data.get("mode", "off"),
        sample_rate=float(data.get("sample_rate", 0.2)),
        always_judge_grade_a=bool(data.get("always_judge_grade_a", True)),
        always_judge_low_confidence=float(data.get("always_judge_low_confidence", 0.7)),
        weights=data.get("weights", QualitySettings().weights),
        threshold_pass=float(data.get("threshold_pass", 0.7)),
        max_retries=int(data.get("max_retries", 1)),
    )


def _config_path(project_root: Path) -> Path:
    """Per-project quality config location (falls back to cwd if no project)."""
    return Path(project_root) / ".index" / "quality_settings.json"

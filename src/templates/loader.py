"""Template loader (bundled + user custom)."""
from dataclasses import dataclass
from pathlib import Path

BUNDLED_DIR = Path(__file__).parent / "bundled"
USER_DIR = Path.home() / ".config" / "ruflo-kb" / "templates"


@dataclass
class Template:
    name: str
    files: dict[str, str]  # relative path → content


def load(name: str) -> Template:
    """Load template by name. Try bundled first, then user dir."""
    bundled = BUNDLED_DIR / name
    if bundled.is_dir():
        files = {
            f.relative_to(bundled).as_posix(): f.read_text(encoding="utf-8")
            for f in bundled.rglob("*") if f.is_file()
        }
        return Template(name=name, files=files)
    user = USER_DIR / name
    if user.is_dir():
        files = {
            f.relative_to(user).as_posix(): f.read_text(encoding="utf-8")
            for f in user.rglob("*") if f.is_file()
        }
        return Template(name=name, files=files)
    raise FileNotFoundError(f"Template not found: {name}")


def list_bundled() -> list[str]:
    """List all bundled template names."""
    if not BUNDLED_DIR.exists():
        return []
    return sorted([d.name for d in BUNDLED_DIR.iterdir() if d.is_dir()])

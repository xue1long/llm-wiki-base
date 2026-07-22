"""Vision CLI: list media pages, manually extract from a file."""
import argparse
import asyncio
import sys
from pathlib import Path

from ..vision.extractor import extract_from_pdf
from ..vision.captioner import VisionCaptioner
from ..vision.storage import MediaPage


def cmd_vision_list(args: argparse.Namespace) -> None:
    """List media pages under <root>/wiki/media/."""
    root = Path(args.project_root) if args.project_root else Path.cwd()
    media_dir = root / "wiki" / "media"
    if not media_dir.exists():
        print("No media pages.")
        return
    count = 0
    for f in sorted(media_dir.glob("*.md")):
        print(f"  {f.name}")
        count += 1
    print(f"\nTotal: {count} media pages")


def cmd_vision_extract(args: argparse.Namespace) -> None:
    """Manually extract + caption a PDF."""
    pdf_path = Path(args.path)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}", file=sys.stderr)
        sys.exit(2)
    root = Path(args.project_root) if args.project_root else Path.cwd()
    task_id = args.task_id or pdf_path.stem

    images = extract_from_pdf(pdf_path, task_id=task_id)
    print(f"Extracted {len(images)} images")
    if not images:
        return
    try:
        captioner = VisionCaptioner(
            provider_registry_name=args.provider or "openai",
            model=args.model or "gpt-4o-mini",
        )
        captions = asyncio.run(captioner.caption_batch(images))
    except Exception as e:
        print(f"Captioning failed: {e}", file=sys.stderr)
        sys.exit(2)
    for img, cap in zip(images, captions):
        MediaPage.write(root, img, cap)
    print(f"Wrote {len(captions)} media pages under {root / 'wiki' / 'media'}")

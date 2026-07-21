# Vision / Image Input Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 2bc246d, post-CLI-UX-polish spec)

## Goal

Add multimodal image understanding to ruflo-kb's ingest pipeline. PDF, EPUB, and Office documents are scanned for embedded images; each image is sent to a vision-capable LLM (or a separate vision model) to generate a factual caption; the caption and the image are persisted in `wiki/media/` as a typed wiki page; related source/analysis pages embed image links.

This unlocks image-aware search (find pages by what's depicted in their images) and visual review (lightbox preview in chat, jump-to-source from images).

## Non-goals

- No video frame extraction (deferred).
- No OCR-as-primary (vision LLM is the source of truth; OCR only as fallback for non-LLM environments).
- No image generation / synthesis (deferred).
- No custom vision model training (use provider's hosted vision).
- No image editing / annotation UI (deferred; no GUI in this spec).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `ImageExtractor` (PDF → images)
- `VisionCaptioner` (LLM)
- `MediaPage` wiki page type
- Image-aware search enhancement

**This spec requires from other specs**:

- **Wiki v2.0 (REQUIRED)**: writes `wiki/media/<id>.md` + image links in source page
- **Multi-Provider LLM (REQUIRED)**: vision-capable model (gpt-4o-mini / claude-haiku-4-5)

**Phase**: Phase 3 — Media
**Priority**: P2 — v2.1

## Architecture

```
Collector fetches PDF/EPUB/Office
   │
   ▼
Image extractor (pdfplumber / python-docx / openpyxl / ebooklib)
   │
   ▼
For each embedded image:
   1. Save raw bytes to wiki/media/<task_id>_<n>.<ext>
   2. Encode as base64 data URL
   3. Call vision-capable LLM (OpenAI gpt-4o-mini / Anthropic claude-haiku-4-5 with vision)
   4. LLM returns caption + alt text + relevant entities mentioned in image
   5. Write wiki/media/<task_id>_<n>.md with frontmatter:
      - type: media
      - id: <task_id>_<n>
      - sources: [raw/sources/<task_id>.<ext>]
      - caption: <LLM caption>
      - alt_text: <short alt>
      - image: media/<task_id>_<n>.<ext>  (relative path)
   6. Update source page to embed ![<alt>](media/<task_id>_<n>.<ext>) inline

Concurrency: max 5 images per task in parallel.
Cost gate: skip vision analysis if task already has > 20 images (configurable).
```

## Components

### New modules

```
src/vision/
├── __init__.py
├── extractor.py          # ImageExtractor per format
├── captioner.py          # VisionCaptioner (LLM calls)
├── storage.py            # MediaStorage (wiki/media/)
└── providers/
    ├── __init__.py
    ├── base.py           # VisionProvider protocol
    ├── openai_vision.py   # gpt-4o-mini / gpt-4-vision
    └── anthropic_vision.py  # claude-haiku-4-5 with vision

tests/test_vision/
├── test_extractor.py
├── test_captioner.py
├── test_storage.py
└── test_providers/
    ├── test_openai_vision.py
    └── test_anthropic_vision.py
```

### Modified modules

| Path | Change |
|---|---|
| `pyproject.toml` | Add `pdfplumber>=0.10` (PDF images); `python-pptx>=0.6` (PPTX); `openpyxl>=3.1` (already for data); `Pillow>=10.0` (image processing); `ebooklib>=0.18` (EPUB) |
| `src/project/settings.py` | `LLMSettings` add `vision_provider: str = "openai"`, `vision_model: str = "gpt-4o-mini"` |
| `src/pipeline/processor.py` | After Generator produces source page, enqueue image extraction task |
| `src/wiki/page_writer.py` | `write_media_page(media_page)` writes to `wiki/media/` |
| `src/wiki/templates.py` | `render_media_page(page)` template |

## Data structures

```python
# src/vision/types.py
@dataclass
class ExtractedImage:
    task_id: str
    index: int                              # nth image in this task
    bytes: bytes
    mime_type: str                          # "image/png" | "image/jpeg" | etc.
    source_page: str                        # "wiki/sources/<task_id>.md"
    context: str                            # surrounding text from PDF (helps captioning)

@dataclass
class ImageCaption:
    task_id: str
    index: int
    caption: str                            # 1-3 sentence factual description
    alt_text: str                           # short alt (< 100 chars)
    entities: list[str]                     # entities mentioned in image
    confidence: float                       # LLM confidence 0-1
    model_used: str
    generated_at: int

@dataclass
class MediaPage:
    id: str                                  # "<task_id>_<n>"
    file_path: str                           # "wiki/media/<task_id>_<n>.<ext>"
    caption: str
    alt_text: str
    entities: list[str]
    sources: list[str]                       # raw source paths
    task_id: str
    image_index: int
    created_at: int
```

```python
# src/vision/extractor.py
class ImageExtractor:
    """Extract images from PDF, Office, EPUB."""
    
    def extract_from_pdf(self, path: Path, task_id: str) -> list[ExtractedImage]:
        """pdfplumber: page.images + page.chars for context."""
        images = []
        with pdfplumber.open(path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                for img_idx, img in enumerate(page.images):
                    # Get image bytes (pdfplumber gives stream)
                    bytes_data = img.to_image(resolution=150).original.format(img["object"])
                    # Get surrounding text (helps captioning)
                    context = page.chars[max(0, img["top"]-100):img["bottom"]+100]
                    context_text = "".join(c["text"] for c in context)
                    images.append(ExtractedImage(
                        task_id=task_id,
                        index=len(images),
                        bytes=bytes_data,
                        mime_type="image/png",
                        source_page=f"wiki/sources/{task_id}.md",
                        context=context_text,
                    ))
        return images
    
    def extract_from_docx(self, path: Path, task_id: str) -> list[ExtractedImage]:
        """python-docx: iterate document.inline_shapes."""
        ...
    
    def extract_from_pptx(self, path: Path, task_id: str) -> list[ExtractedImage]:
        """python-pptx: slide.shapes where shape.shape_type == PICTURE."""
        ...
    
    def extract_from_epub(self, path: Path, task_id: str) -> list[ExtractedImage]:
        """ebooklib: chapter content images."""
        ...

class ImageExtractionPipeline:
    def extract(self, source_path: Path, task_id: str) -> list[ExtractedImage]:
        ext = source_path.suffix.lower()
        if ext == ".pdf":
            return self.extract_from_pdf(source_path, task_id)
        elif ext in (".docx", ".doc"):
            return self.extract_from_docx(source_path, task_id)
        elif ext in (".pptx", ".ppt"):
            return self.extract_from_pptx(source_path, task_id)
        elif ext in (".epub", ".mobi"):
            return self.extract_from_epub(source_path, task_id)
        else:
            return []
```

```python
# src/vision/captioner.py
class VisionCaptioner:
    MAX_CONCURRENT = 5
    MAX_IMAGES_PER_TASK = 20
    
    async def caption_batch(
        self,
        ctx: ProjectContext,
        images: list[ExtractedImage],
    ) -> list[ImageCaption]:
        if len(images) > self.MAX_IMAGES_PER_TASK:
            logger.warning(f"[Vision] Task has {len(images)} images; skipping analysis for first {self.MAX_IMAGES_PER_TASK}")
            images = images[:self.MAX_IMAGES_PER_TASK]
        
        provider = self._get_provider(ctx)
        sem = asyncio.Semaphore(self.MAX_CONCURRENT)
        
        async def caption_one(img: ExtractedImage) -> ImageCaption:
            async with sem:
                try:
                    response = await provider.caption_image(img.bytes, img.mime_type, img.context)
                    return ImageCaption(
                        task_id=img.task_id,
                        index=img.index,
                        caption=response["caption"],
                        alt_text=response["alt_text"],
                        entities=response.get("entities", []),
                        confidence=response.get("confidence", 0.8),
                        model_used=ctx.settings.llm.vision_model,
                        generated_at=int(time.time() * 1000),
                    )
                except Exception as e:
                    return ImageCaption(
                        task_id=img.task_id,
                        index=img.index,
                        caption=f"[Image extraction failed: {e}]",
                        alt_text="Image (caption failed)",
                        entities=[],
                        confidence=0.0,
                        model_used=ctx.settings.llm.vision_model,
                        generated_at=int(time.time() * 1000),
                    )
        
        return await asyncio.gather(*[caption_one(img) for img in images])
```

```python
# src/vision/providers/openai_vision.py
class OpenAIVisionProvider:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=60)
    
    async def caption_image(self, image_bytes: bytes, mime_type: str, context: str) -> dict:
        import base64
        b64 = base64.b64encode(image_bytes).decode()
        
        response = await self.client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CAPTION_PROMPT.format(context=context[:2000])},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    ],
                }],
                "response_format": CAPTION_SCHEMA,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

CAPTION_PROMPT = """Describe this image factually and concisely.

Context (surrounding text):
{context}

Output JSON:
{{
  "caption": "<1-3 sentence factual description>",
  "alt_text": "<short alt, < 100 chars>",
  "entities": ["<named entities in image>"],
  "confidence": <0.0-1.0>
}}"""

CAPTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "image_caption",
        "schema": {
            "type": "object",
            "properties": {
                "caption": {"type": "string"},
                "alt_text": {"type": "string"},
                "entities": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            },
            "required": ["caption", "alt_text"],
        },
    },
}
```

## Storage layout

```
wiki/media/
├── <task_id>_0.png
├── <task_id>_0.md
├── <task_id>_1.jpg
├── <task_id>_1.md
└── ...
```

```markdown
---
title: Figure 1 from <task_id>
type: media
id: <task_id>_0
sources: [raw/sources/<task_id>.pdf]
caption: <LLM-generated caption>
alt_text: <short alt>
entities: [entity-a, entity-b]
confidence: 0.92
created_at: <ts>
image: media/<task_id>_0.png
---

# Figure 1 from <task_id>

![<alt_text>](media/<task_id>_0.png)

<caption as paragraph>
```

## Pipeline integration

```python
# src/pipeline/processor.py (modified)
async def generate(ctx, analysis):
    pages = await self._call_llm_generate(ctx, analysis)
    
    # Existing page write
    for page in pages:
        ctx.page_writer.write(page)
    
    # NEW: extract + caption images from raw source
    raw_path = ctx.paths.raw_sources / f"{ctx.task_id}{analysis.source_ext}"
    if raw_path.exists() and analysis.source_ext in {".pdf", ".docx", ".pptx", ".epub"}:
        extractor = ImageExtractor()
        images = extractor.extract(raw_path, ctx.task_id)
        if images:
            captioner = VisionCaptioner()
            captions = await captioner.caption_batch(ctx, images)
            # Write media pages
            for img, cap in zip(images, captions):
                # Save image bytes
                media_path = ctx.paths.wiki_media / f"{ctx.task_id}_{img.index}.{img.mime_type.split('/')[-1]}"
                media_path.parent.mkdir(parents=True, exist_ok=True)
                media_path.write_bytes(img.bytes)
                # Write media page
                media_page = MediaPage(
                    id=f"{ctx.task_id}_{img.index}",
                    file_path=f"wiki/media/{ctx.task_id}_{img.index}.{img.mime_type.split('/')[-1]}",
                    caption=cap.caption,
                    alt_text=cap.alt_text,
                    entities=cap.entities,
                    sources=[f"raw/sources/{ctx.task_id}{analysis.source_ext}"],
                    task_id=ctx.task_id,
                    image_index=img.index,
                    created_at=int(time.time() * 1000),
                )
                page_writer.write_media_page(media_page)
            
            # Embed image links in source page
            for cap in captions:
                source_page_path = ctx.paths.wiki_sources / f"{ctx.task_id}.md"
                if source_page_path.exists():
                    content = source_page_path.read_text(encoding="utf-8")
                    img_link = f"\n\n![{cap.alt_text}](media/{ctx.task_id}_{cap.image_index}.png)"
                    if img_link not in content:
                        source_page_path.write_text(content + img_link, encoding="utf-8")
```

## CLI surface

```
python -m src.cli config set llm.vision_model gpt-4o-mini --project <id>
python -m src.cli config set llm.vision_provider openai --project <id>

python -m src.cli vision extract <file_path>           # Manual image extraction + captioning
python -m src.cli vision list [--project <id>]         # List all media pages
python -m src.cli vision show <media_id>                # Show media page content
```

## HTTP + MCP

```
GET    /api/v1/projects/{id}/media                      # List all media
GET    /api/v1/projects/{id}/media/{mid}                # Get media page
GET    /api/v1/projects/{id}/media/{mid}/image          # Get raw image bytes (binary)
POST   /api/v1/projects/{id}/media/extract              # Manually trigger extraction on a source

MCP tools:
ruflo_kb_media_list(project_id)
ruflo_kb_media_show(project_id, media_id)
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Image extraction | pdfplumber/python-docx missing | Hard error: "pip install ruflo-kb[vision]" |
| Image extraction | Corrupt PDF | Skip + warning; continue with other pages |
| Image extraction | No images found | Normal — return empty list |
| Vision LLM | Timeout / API error | Image gets fallback caption "[Image extraction failed: <reason>]"; pipeline continues |
| Vision LLM | Image too large | Resize to < 5MB using Pillow; if still too large, skip + log |
| Storage write | Disk full | Hard error; source page doesn't get image links |
| Embedding in source page | Image link already present | Skip (idempotent) |
| Concurrent limit | > 5 images in parallel | Queue + wait for semaphore |
| Max images per task | > 20 images | Process first 20; log "X more images skipped" |
| Vision provider not configured | No API key | Skip vision entirely; images saved to wiki/media/ without captions |
| Unsupported file type | .txt / .md / .html | No images extracted; OK |

## Backwards compatibility

- Vision is opt-in: defaults to enabled in `settings.llm.vision_enabled = True`, but if vision provider not configured, gracefully skips.
- Existing PDF ingest without vision: unchanged (just no media pages created).
- New `wiki/media/` directory: created on first vision extraction.
- New dependencies are all `pip install ruflo-kb[vision]` extras (optional).

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/vision/extractor.py` | PDF / DOCX / PPTX / EPUB extraction; corrupt file handling |
| `src/vision/captioner.py` | Concurrent batch; max images cap; failure fallback caption |
| `src/vision/providers/openai_vision.py` | httpx mock; base64 encoding; prompt + schema |
| `src/vision/providers/anthropic_vision.py` | httpx mock; vision message format |
| `src/vision/storage.py` | wiki/media/ path resolution; collision avoidance |

### Integration tests

```
tests/test_integration/test_vision_e2e.py:
    def test_pdf_image_extraction_and_captioning():
        # Mock OpenAIVisionProvider; provide test PDF with 2 images
        # Run ingest
        # Verify: 2 images in wiki/media/, 2 .md pages, source page has 2 image links

    def test_max_images_per_task_limit():
        # Provide PDF with 25 images; config limit 20
        # Verify: 20 images processed, 5 logged as skipped

    def test_vision_provider_failure_graceful_degradation():
        # Mock provider raises timeout
        # Verify: images saved without captions; ingest completes

    def test_no_images_in_source():
        # Plain text PDF (no images)
        # Verify: vision skipped; no errors
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P2)

- PDF only (pdfplumber + Pillow)
- GPT-4o-mini / Claude vision models
- 20 images/task max, 5 concurrent
- `wiki/media/` storage + .md caption pages
- Image links embedded in source page

### Polish (v2.0.1 or later)

- DOCX / PPTX / EPUB extractors
- Image rerank in search results
- Per-image diff tracking

### Deferred (v2.1+)

- Video frame extraction
- OCR fallback
- Image generation
- Image embedding (CLIP)

## Implementation order

5 phases:

1. **Foundation** — `src/vision/types.py` + `ProjectSettings.vision_*` + `pyproject.toml` extras
2. **Image extractor** — `src/vision/extractor.py` (PDF first; others stub) + tests
3. **Vision providers** — `src/vision/providers/{openai,anthropic}_vision.py` + tests
4. **Captioner + storage** — `src/vision/captioner.py` + `storage.py` + pipeline integration + tests
5. **CLI + HTTP + MCP** — `cmd_vision` + HTTP endpoints + MCP tools + integration tests

## Cost estimation

- Per image: ~$0.001-0.005 (gpt-4o-mini / claude-haiku-4-5 vision)
- Typical PDF with 5-10 images: +$0.005-0.05 per ingest
- Vision prompt: ~500 tokens input (image + context) + ~150 tokens output

## Open questions / deferred

- Video frame extraction (cv2 / ffmpeg).
- OCR-as-primary for scanned PDFs.
- Image generation / DALL-E integration.
- Image embedding for visual similarity search (CLIP / imagebind).
- Lightbox / annotation UI.
- Image cropping / region-of-interest.
- Multi-page image stitching (for diagrams split across pages).
- Per-image diff tracking (re-caption if source changes).
- Vision provider Ollama (llava, llama3.2-vision) — separate sub-spec.
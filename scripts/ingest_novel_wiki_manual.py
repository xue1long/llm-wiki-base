import asyncio, sys, time
from pathlib import Path
ROOT = r"E:\2026-7-21\ruflo-kb"
sys.path.insert(0, ROOT)

import src.pipeline.pipeline as m
from src.llm.types import ProviderConfig
from src.llm.ollama_provider import OllamaProvider, LLMResponse

PROJECT_ID = "8dd46257-e46d-4bf8-b8d8-ba60b2aea54d"
MODEL = "qwen3.5-9b-uncensored-hauhaucs-aggressive-q6_k:latest"
base = Path(r"E:\2026-7-21\ruflo-kb\knowledge\novel-wiki\raw\sources")
files = [
    "补充教程写作经验如何加强书的情节.md",
    "补充教程写穿越小说角色前要注意的十个问题.md",
    "补充教程小说写作大纲的模版共享.md",
    "补充教程小说写作新人网络小说的成神宝典精装版.md",
    "补充教程小说结局的十三种方式精.md",
]

# qwen3.5-uncensored via ollama returns EMPTY/truncated unless we pin
# num_predict high AND a working seed (default num_predict truncates;
# the model emits empty intermittently). Rotate seeds on empty.
# FIX for qwen3.5-uncensored empty-content: ollama defaults num_ctx=4096,
# leaving ~2446 tokens for generation — all consumed by the model's
# mandatory "Thinking Process" preamble, so the JSON never gets emitted
# and /api/chat returns empty. Raise num_ctx so thinking + JSON fit; the
# chat template strips the thinking and returns clean JSON. Drop
# response_format (format:json is unnecessary and was flaky).
class OllamaStable(OllamaProvider):
    OPTS = [
        {"temperature": 0, "num_predict": 8192, "num_ctx": 49152, "seed": 42},
        {"temperature": 0, "num_predict": 8192, "num_ctx": 49152, "seed": 7},
        {"temperature": 0.1, "num_predict": 8192, "num_ctx": 49152, "seed": 11},
    ]
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._i = 0
    async def complete(self, messages, *, response_format=None, system=None, **kw):
        body = {"model": self.model, "messages": list(messages), "stream": False}
        if system:
            body["messages"] = [{"role": "system", "content": system}] + body["messages"]
        last = None
        for _ in range(3):  # rotate seeds on empty
            opt = dict(self.OPTS[self._i % len(self.OPTS)])
            self._i += 1
            opt["repeat_penalty"] = 1.1
            body["options"] = opt
            try:
                r = await self.client.post(f"{self.base_url}/api/chat", json=body)
                r.raise_for_status()
                d = r.json()
                c = (d.get("message", {}).get("content") or "").strip()
                if c:
                    return LLMResponse(content=c, model=self.model, usage={})
                last = "empty"
            except Exception as e:
                last = e
        raise RuntimeError(f"ollama stable failed ({last})")

def make_provider():
    cfg = ProviderConfig(name="ollama-local", type="ollama",
        base_url="http://127.0.0.1:11434",
        default_chat_model=MODEL, timeout_seconds=600)
    return OllamaStable(cfg)

async def ingest_one(paths, provider, sp, text, tid, max_retries=2):
    delay = 15
    for attempt in range(1, max_retries + 1):
        try:
            return await m.run_ingest(paths=paths, source_path=sp,
                source_text=text, provider=provider, task_id=tid)
        except Exception as e:
            print(f"   [retry {attempt}] {type(e).__name__}: {str(e)[:160]}", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 90)
    raise RuntimeError(f"exhausted retries for {tid}")

async def main():
    if len(sys.argv) == 1:
        targets = files  # all
    elif len(sys.argv) == 2:
        targets = [files[int(sys.argv[1]) - 1]]  # single file (1-based)
    else:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        targets = files[start - 1 : end]
    paths = m._resolve_wiki_paths(project_id=PROJECT_ID)
    provider = make_provider()
    print("PROVIDER: OllamaStable ->", MODEL, flush=True)
    for idx_in_all, fname in enumerate(targets):
        i = files.index(fname) + 1  # 1-based index
        sp = base / fname
        text = sp.read_text(encoding="utf-8")
        t0 = time.time()
        print(f"--- [{i}/5] {fname} ({len(text)} chars) ---", flush=True)
        pages = await ingest_one(paths, provider, sp, text, f"ollama-{i}")
        print(f"    -> {len(pages)} pages in {time.time()-t0:.0f}s", flush=True)
        if idx_in_all < len(targets) - 1:
            await asyncio.sleep(10)
    print("DONE ALL", flush=True)

if __name__ == "__main__":
    asyncio.run(main())

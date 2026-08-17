import asyncio
import json
import httpx
import os

async def main():
    cfg_path = os.environ["LOCALAPPDATA"] + r"\ruflo-kb\ruflo-kb\llm-providers.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    minimax = cfg["providers"]["minimax"]
    api_key = minimax["api_key"]
    print("Model:", minimax.get("default_chat_model"))

    # Use the ACTUAL Generator prompt template
    test_content = (
        'Say only this JSON: {"test": 1} — return JSON only, no extra text. '
        'Respond in Chinese if possible.'
    )

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.minimax.chat/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": minimax.get("default_chat_model", "MiniMax-M3"),
                "messages": [{"role": "user", "content": test_content}],
            },
        )
        print("Status:", resp.status_code)
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        print("Content type:", type(content).__name__, "len:", len(content))
        print("Content repr:", repr(content[:400]))
        print("Starts with JSON?:", content.strip().startswith("{"))
        try:
            json.loads(content.strip())
            print("JSON parse OK")
        except Exception as e:
            print("JSON parse FAIL:", e)

asyncio.run(main())

"""HTTP client wrapping the FastAPI server (MCP uses HTTP under the hood)."""
import httpx


class RufloKbAPIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:19828"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30)

    async def health(self) -> dict:
        r = await self.client.get("/health")
        r.raise_for_status()
        return r.json()

    async def projects(self) -> dict:
        r = await self.client.get("/api/v1/projects")
        r.raise_for_status()
        return r.json()

    async def search(self, project_id: str, query: str, top_k: int = 10) -> dict:
        r = await self.client.post(f"/api/v1/projects/{project_id}/search",
                                    json={"query": query, "topK": top_k})
        r.raise_for_status()
        return r.json()

    async def files(self, project_id: str, root: str = "wiki", max_files: int = 200) -> dict:
        r = await self.client.get(f"/api/v1/projects/{project_id}/files",
                                    params={"root": root, "max_files": max_files})
        r.raise_for_status()
        return r.json()

    async def file_content(self, project_id: str, path: str) -> dict:
        r = await self.client.get(f"/api/v1/projects/{project_id}/files/content",
                                    params={"path": path})
        r.raise_for_status()
        return r.json()

    async def reviews(self, project_id: str, status: str = "open") -> dict:
        r = await self.client.get(f"/api/v1/projects/{project_id}/reviews",
                                    params={"status": status})
        r.raise_for_status()
        return r.json()

    async def ingest(self, project_id: str, source: str) -> dict:
        r = await self.client.post(f"/api/v1/projects/{project_id}/ingest",
                                    json={"source": source})
        r.raise_for_status()
        return r.json()

    async def chat(self, project_id: str, message: str) -> dict:
        r = await self.client.post(f"/api/v1/projects/{project_id}/chat",
                                    json={"message": message})
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self.client.aclose()

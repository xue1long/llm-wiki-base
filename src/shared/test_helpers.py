class ScriptedLLMProvider:
    """Mock LLM provider that returns scripted_responses in order."""

    def __init__(self, scripted_responses: list):
        self.scripted = list(scripted_responses)
        self.calls: list = []

    async def complete(self, prompt, response_format=None, system=None, **kwargs):
        self.calls.append({"prompt": prompt, "schema": response_format})
        if not self.scripted:
            raise RuntimeError(f"Mock LLM exhausted (calls: {len(self.calls)})")
        return self.scripted.pop(0)

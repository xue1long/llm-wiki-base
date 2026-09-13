"""Contract tests for the read-only Claude Code/GBrain host."""
import json


def test_build_mcp_config_scopes_source_and_uses_explicit_bun(tmp_path):
    from src.agent.claude_host import build_mcp_config

    config = build_mcp_config(
        tmp_path,
        source_id="ruflo-demo",
        bun_path=r"C:\Users\HP\.bun\bin\bun.exe",
        runtime_path=r"C:\gbrain\v0.50.0.0",
    )

    server = config["mcpServers"]["gbrain"]
    assert server["env"] == {"GBRAIN_SOURCE": "ruflo-demo"}
    assert server["command"].lower().endswith("cmd.exe")
    assert r"C:\Users\HP\.bun\bin\bun.exe" in server["args"][-1]
    assert r"C:\gbrain\v0.50.0.0" in server["args"][-1]


def test_parse_claude_json_envelope_and_answer_payload():
    from src.agent.claude_host import parse_claude_output

    answer = {"answer": "依据知识库回答", "references": [{"slug": "concepts/a"}]}
    envelope = {"type": "result", "is_error": False, "result": json.dumps(answer, ensure_ascii=False)}

    parsed = parse_claude_output("warning\n" + json.dumps(envelope, ensure_ascii=False))

    assert parsed["answer"] == "依据知识库回答"
    assert parsed["references"] == [{"slug": "concepts/a"}]


def test_parse_nested_json_answer_payload():
    from src.agent.claude_host import parse_claude_output

    nested = json.dumps({"answer": "嵌套回答", "references": [{"slug": "concepts/a"}]}, ensure_ascii=False)
    envelope = {"type": "result", "is_error": False, "result": json.dumps({"answer": nested})}

    parsed = parse_claude_output(json.dumps(envelope))

    assert parsed["answer"] == "嵌套回答"
    assert parsed["references"] == [{"slug": "concepts/a"}]


def test_read_only_tool_names_are_fixed():
    from src.agent.claude_host import READ_ONLY_TOOLS

    assert READ_ONLY_TOOLS == ("mcp__gbrain__search", "mcp__gbrain__get_page")
    assert not any("put" in name or "delete" in name for name in READ_ONLY_TOOLS)


def test_prompt_requests_markdown_answer():
    from src.agent.claude_host import _prompt

    assert "answer 必须使用" in _prompt("问题", "ruflo-demo")
    assert "Markdown" in _prompt("问题", "ruflo-demo")

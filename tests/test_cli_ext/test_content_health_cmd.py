import argparse
import json

from src.cli_ext.content_health_cmd import cmd_content_health
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def test_content_health_cli_json(tmp_path, capsys):
    ensure_knowledge_base(tmp_path)
    write_page(WikiPaths(tmp_path), WikiPage(
        id="health-cli", title="Health", type=PageType.CONCEPT, body="body"
    ))

    cmd_content_health(argparse.Namespace(project=str(tmp_path), json=True))

    report = json.loads(capsys.readouterr().out)
    assert report["page_count"] == 1

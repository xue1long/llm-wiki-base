"""Tests for CLI capture subcommand."""
import argparse
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestCaptureCLI:
    """Unit tests for CLI capture command."""

    def test_capture_cli_invalid_type(self):
        """--type must be one of article/video-transcript/inspiration."""
        from src.cli_ext.capture_cmd import register
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)
        with pytest.raises(SystemExit):
            parser.parse_args(["capture", "--type", "foo", "--title", "test"])

    def test_capture_cli_missing_title(self):
        """--title is required."""
        from src.cli_ext.capture_cmd import register
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)
        with pytest.raises(SystemExit):
            parser.parse_args(["capture", "--type", "article"])

    def test_capture_cli_article_args(self):
        """Valid article capture args are parsed correctly."""
        from src.cli_ext.capture_cmd import register
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)
        args = parser.parse_args([
            "capture", "--type", "article", "--title", "Test",
            "--content", "hello", "--url", "https://example.com",
        ])
        assert args.type == "article"
        assert args.title == "Test"
        assert args.content == "hello"
        assert args.url == "https://example.com"

    def test_capture_cli_tags_comma_split(self):
        """--tags are comma-separated."""
        from src.cli_ext.capture_cmd import register
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)
        args = parser.parse_args([
            "capture", "--type", "article", "--title", "Test",
            "--tags", "a,b,c",
        ])
        assert args.tags == "a,b,c"
        # Actual splitting happens in cmd_capture, test there
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        assert tags == ["a", "b", "c"]

    def test_capture_cli_inspiration_no_content(self):
        """Inspiration capture without content creates skeleton."""
        from src.cli_ext.capture_cmd import register
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register(subparsers)
        args = parser.parse_args([
            "capture", "--type", "inspiration", "--title", "Great Idea",
        ])
        assert args.type == "inspiration"
        assert args.content is None
        assert args.file is None
        assert args.stdin is False

    @patch("src.services.capture.capture_page")
    def test_capture_cli_calls_service(self, mock_capture):
        """CLI calls capture_page with correct arguments."""
        mock_capture.return_value = {
            "status": "ok", "page_id": "card_test", "path": "/test", "is_skeleton": False,
        }
        from src.cli_ext.capture_cmd import cmd_capture
        args = argparse.Namespace(
            type="article", title="Test", content="hello",
            file=None, stdin=False, url="https://example.com",
            tags="a,b", category="", project=".", path=None,
        )
        cmd_capture(args)
        mock_capture.assert_called_once_with(
            project_id=".", type="article", title="Test",
            content="hello", url="https://example.com",
            tags=["a", "b"], category="",
        )

    def test_capture_cli_file_not_found(self):
        """--file that doesn't exist exits with error."""
        from src.cli_ext.capture_cmd import cmd_capture
        args = argparse.Namespace(
            type="article", title="Test", content=None,
            file="/nonexistent/file.txt", stdin=False,
            url=None, tags=None, category="", project=".", path=None,
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_capture(args)
        assert exc_info.value.code == 1

    @patch("src.services.capture.capture_page")
    def test_capture_cli_service_error(self, mock_capture):
        """Service ValueError exits with error."""
        mock_capture.side_effect = ValueError("Invalid capture type")
        from src.cli_ext.capture_cmd import cmd_capture
        args = argparse.Namespace(
            type="article", title="Test", content="",
            file=None, stdin=False, url=None,
            tags=None, category="", project=".", path=None,
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_capture(args)
        assert exc_info.value.code == 1

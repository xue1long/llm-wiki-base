"""Test validators for HTTP API input sanitization.

Covers Round 6 findings:
- Empty source strings
- Path traversal attempts
- Null byte injection
- Control characters
"""
import pytest
from pathlib import Path
from src.lib.validators import (
    validate_source_string,
    validate_file_source,
    validate_url_source,
    validate_source,
)


class TestValidateSourceString:
    """Tests for base string validation."""

    def test_empty_string(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_source_string("")

    def test_whitespace_only(self):
        """Whitespace-only string should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_source_string("   \t\n  ")

    def test_null_byte_injection(self):
        """Null byte should raise ValueError."""
        with pytest.raises(ValueError, match="null byte"):
            validate_source_string("test\x00.md")

    def test_control_characters(self):
        """Control characters should raise ValueError."""
        with pytest.raises(ValueError, match="control character"):
            validate_source_string("test\x01file.md")

    def test_valid_path(self):
        """Valid paths should pass."""
        validate_source_string("raw/sources/test.md")  # No exception

    def test_valid_url(self):
        """Valid URLs should pass."""
        validate_source_string("https://example.com/file.pdf")  # No exception

    def test_url_with_unicode(self):
        """URLs with Unicode characters should pass."""
        validate_source_string("https://example.com/文件.pdf")  # No exception


class TestValidateFileSource:
    """Tests for file path validation."""

    def test_path_traversal_deep(self):
        """Deep traversal should raise ValueError."""
        with pytest.raises(ValueError, match="escape project root"):
            validate_file_source("../../../../../etc/passwd", Path("/project"))

    def test_path_within_project(self):
        """Paths within project should pass."""
        project_root = Path("/project")
        validate_file_source("raw/sources/test.md", project_root)  # No exception

    def test_absolute_path_outside_project(self):
        """Absolute path outside project should raise ValueError."""
        with pytest.raises(ValueError, match="outside project root"):
            validate_file_source("/etc/passwd", Path("/project"))

    def test_null_byte_in_path(self):
        """Null byte in path should raise ValueError."""
        with pytest.raises(ValueError, match="null byte"):
            validate_file_source("test\x00.md", Path("/project"))


class TestValidateUrlSource:
    """Tests for URL validation."""

    def test_valid_http_url(self):
        """Valid HTTP URL should pass."""
        validate_url_source("http://example.com/file.pdf")  # No exception

    def test_valid_https_url(self):
        """Valid HTTPS URL should pass."""
        validate_url_source("https://example.com/file.pdf")  # No exception

    def test_invalid_scheme(self):
        """Non-HTTP(S) scheme should raise ValueError."""
        with pytest.raises(ValueError, match="scheme must be http or https"):
            validate_url_source("ftp://example.com/file.pdf")

    def test_missing_hostname(self):
        """URL without hostname should raise ValueError."""
        with pytest.raises(ValueError, match="no hostname"):
            validate_url_source("https:///file.pdf")

    def test_url_with_credentials(self):
        """URL with embedded credentials should raise ValueError."""
        with pytest.raises(ValueError, match="embedded credentials"):
            validate_url_source("https://user:pass@example.com/file.pdf")


class TestValidateSource:
    """Tests for main entry point."""

    def test_url_routing(self):
        """URLs should be routed to URL validator."""
        validate_source("https://example.com/file.pdf")  # No exception

    def test_file_routing(self):
        """File paths should be routed to file validator."""
        validate_source("raw/sources/test.md", Path("/project"))  # No exception

    def test_empty_source(self):
        """Empty source should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_source("")

    def test_file_without_project_root(self):
        """File path without project root should do basic validation."""
        # Should NOT raise - just does basic string validation
        validate_source("raw/sources/test.md")  # No exception

        # Should raise on null byte
        with pytest.raises(ValueError, match="null byte"):
            validate_source("test\x00.md")


class TestEdgeCases:
    """Edge case tests from Round 6 pressure test."""

    def test_path_traversal_3_levels(self):
        """Traversal of exactly 3 levels should pass (project root is ~2-3 levels above raw/sources/)."""
        # This should NOT raise - legitimate path like "../../../project/raw/sources/file.md"
        validate_source_string("../../../project/raw/sources/file.md")

    def test_path_traversal_4_levels(self):
        """Traversal of 4+ levels should raise."""
        with pytest.raises(ValueError, match="escape project root"):
            validate_source_string("../../../../etc/passwd")

    def test_empty_after_normalization(self):
        """Path that normalizes to empty should pass basic validation.

        Note: "." normalizes to current directory, which is valid.
        The empty check only triggers on literal empty strings.
        """
        validate_source_string(".")  # No exception - valid

    def test_unicode_path(self):
        """CJK path should pass basic validation."""
        validate_source_string("raw/sources/01_新手入门/3_开篇.md")  # No exception

    def test_url_with_port(self):
        """URL with port should pass."""
        validate_url_source("https://example.com:8080/file.pdf")  # No exception

    def test_url_with_query(self):
        """URL with query string should pass."""
        validate_url_source("https://example.com/file.pdf?version=2")  # No exception
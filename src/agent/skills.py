"""Agent Skills system — dynamic skill loading from SKILL.md files.

Phase 4.2 of the Nash absorption plan.
Skills allow users to extend Agent capabilities without modifying core code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..agent.types import AgentConfig


@dataclass
class Skill:
    """A loaded skill definition."""

    name: str
    description: str
    instructions: str
    tools: list[str] = field(default_factory=list)  # Required tools
    path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "tools": self.tools,
            "path": str(self.path) if self.path else None,
        }


# Skill name validation pattern
SKILL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def parse_skill_file(path: Path) -> Skill | None:
    """Parse a SKILL.md file into a Skill object.

    SKILL.md format:
    ```
    # skill-name

    Short description of the skill.

    ## Tools
    - wiki.search
    - web.search

    ## Instructions
    Detailed instructions for the LLM...
    ```

    Args:
        path: Path to SKILL.md file

    Returns:
        Skill object or None if parsing fails
    """
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return None

    lines = content.split("\n")

    # First heading is the skill name
    name = ""
    for line in lines:
        if line.startswith("# "):
            name = line[2:].strip().lower()
            # Normalize: replace spaces with hyphens
            name = re.sub(r"\s+", "-", name)
            break

    if not name or not SKILL_NAME_PATTERN.match(name):
        return None

    # Extract sections
    description = ""
    tools: list[str] = []
    instructions = ""

    current_section = "description"
    section_lines: list[str] = []

    for line in lines[1:]:  # Skip first line (name)
        if line.startswith("## "):
            # Save previous section
            section_content = "\n".join(section_lines).strip()
            if current_section == "description":
                description = section_content
            elif current_section == "tools":
                # Parse tool list
                for tool_line in section_lines:
                    tool_line = tool_line.strip()
                    if tool_line.startswith("- "):
                        tool_name = tool_line[2:].strip()
                        if tool_name:
                            tools.append(tool_name)

            current_section = line[3:].strip().lower()
            section_lines = []
        else:
            section_lines.append(line)

    # Save last section
    section_content = "\n".join(section_lines).strip()
    if current_section == "instructions":
        instructions = section_content
    elif current_section == "description" and not description:
        description = section_content

    # Instructions can also be the rest of the file after description
    if not instructions and not tools:
        # No formal sections, use rest of content as instructions
        rest_content = content.split("\n", 1)
        if len(rest_content) > 1:
            instructions = rest_content[1].strip()

    return Skill(
        name=name,
        description=description,
        instructions=instructions,
        tools=tools,
        path=path,
    )


class SkillRegistry:
    """Registry for loaded skills."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def load_from_directory(self, dir_path: Path) -> int:
        """Load all SKILL.md files from a directory.

        Args:
            dir_path: Directory to scan

        Returns:
            Number of skills loaded
        """
        if not dir_path.exists():
            return 0

        count = 0
        for skill_file in dir_path.glob("**/SKILL.md"):
            skill = parse_skill_file(skill_file)
            if skill and skill.name:
                self._skills[skill.name] = skill
                count += 1

        return count

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        """List all loaded skills."""
        return list(self._skills.values())

    def has_skill(self, name: str) -> bool:
        """Check if a skill exists."""
        return name in self._skills


# Global registry
_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Get or create the global skill registry."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def load_skills(project_path: Path) -> int:
    """Load skills from project directory.

    Looks for SKILL.md files in:
    - .skills/ directory (project-specific)
    - skills/ directory (user-level)

    Args:
        project_path: Project root path

    Returns:
        Total skills loaded
    """
    registry = get_skill_registry()

    total = 0

    # Project-specific skills
    project_skills_dir = project_path / ".skills"
    total += registry.load_from_directory(project_skills_dir)

    # User-level skills (global)
    user_skills_dir = Path.home() / ".ruflo-kb" / "skills"
    total += registry.load_from_directory(user_skills_dir)

    return total


def get_skill(name: str) -> Skill | None:
    """Get a skill by name from the global registry."""
    return get_skill_registry().get(name)


def list_skills() -> list[Skill]:
    """List all loaded skills."""
    return get_skill_registry().list_skills()


def format_skill_prompt(skill: Skill) -> str:
    """Format a skill for inclusion in LLM prompt.

    Args:
        skill: Skill to format

    Returns:
        Formatted prompt section
    """
    parts = [
        f"## Skill: {skill.name}",
        "",
        skill.description,
        "",
    ]

    if skill.tools:
        parts.append("Required tools:")
        for tool in skill.tools:
            parts.append(f"- {tool}")
        parts.append("")

    if skill.instructions:
        parts.append("Instructions:")
        parts.append(skill.instructions)

    return "\n".join(parts)
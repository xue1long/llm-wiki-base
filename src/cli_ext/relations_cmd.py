"""Wiki relations CLI subcommands."""
import argparse
import sys
from ..wiki.relations import (
    Relation, RelationType, INVERSE_RELATIONS, USER_TYPE_PREFIX,
    RelationSync, RelationQuery,
)
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_relations_list(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    rels = RelationQuery.list_relations(ctx.paths, args.page_id)
    for r in rels:
        print(f"  → {r.target_id}  ({r.type}, w={r.weight})  {r.context}")


def cmd_relations_backlinks(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    rels = RelationQuery.find_backlinks(ctx.paths, args.page_id)
    print(f"Backlinks to {args.page_id}:")
    for r in rels:
        print(f"  ← {r.target_id}  ({r.type}, w={r.weight})")


def cmd_relations_neighbors(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    neighbors = RelationQuery.find_neighbors(ctx.paths, args.page_id, args.depth)
    for nid, via, w in neighbors:
        print(f"  → {nid}  (via {via}, w={w:.2f})")


def cmd_relations_path(args: argparse.Namespace) -> None:
    ctx = _resolve(args.project)
    path = RelationQuery.find_path(ctx.paths, args.from_id, args.to_id)
    if not path:
        print(f"No path from {args.from_id} to {args.to_id}")
        sys.exit(1)
    for f, t, typ in path:
        print(f"  {f} --[{typ}]--> {t}")


def cmd_relations_types(args: argparse.Namespace) -> None:
    """List all known relation types (built-in + user-defined)."""
    print("Built-in types:")
    for t in RelationType:
        inv = INVERSE_RELATIONS.get(t.value, "(symmetric)")
        print(f"  {t.value:<25} (inverse: {inv})")
    # User-defined types from settings
    print("\nUser-defined types (x-):")
    print("  (use `relations add-type <name>` to register)")


def cmd_relations_add_type(args: argparse.Namespace) -> None:
    name = args.name
    if not name.startswith(USER_TYPE_PREFIX):
        name = USER_TYPE_PREFIX + name
    # Register in settings
    config_path = _settings_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        data = __import__("json").loads(config_path.read_text(encoding="utf-8"))
    else:
        data = {}
    types = set(data.get("user_relation_types", []))
    types.add(name)
    data["user_relation_types"] = sorted(types)
    config_path.write_text(__import__("json").dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Registered user relation type: {name}")


def _resolve(project_id):
    try:
        return ProjectContext.resolve(project_id, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(2)


def _settings_path():
    from pathlib import Path
    from ..project.context import ProjectContext, ProjectNotFoundError
    try:
        ctx = ProjectContext.resolve(None)
        return ctx.paths.llm_wiki / "settings.json"
    except ProjectNotFoundError:
        return Path.cwd() / "settings.json"
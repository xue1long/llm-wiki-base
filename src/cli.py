# ruflo-kb/src/cli.py
"""
ruflo-kb CLI 入口.

Subcommands are delegated to the ``src.cli_ext`` modules imported below.
Run ``python -m src.cli --help`` for the full list.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from .project.discovery import auto_register_on_first_run
from .cli_ext.project_cmd import (
    cmd_project_current,
    cmd_project_info,
    cmd_project_init,
    cmd_project_list,
    cmd_project_select,
    cmd_project_import,
    cmd_project_forget,
    cmd_project_rename,
    cmd_project_discover,
    cmd_project_set_provider,
    cmd_project_set_model,
)
from .cli_ext.schema_cmd import (
    cmd_schema_list,
    cmd_schema_diff,
    cmd_schema_upgrade,
    cmd_schema_downgrade,
    cmd_schema_backup,
)
from .cli_ext.atomic_cmd import cmd_atomic_status, cmd_budget_estimate, cmd_budget_check
from .cli_ext.completions_cmd import cmd_completions
from .cli_ext.templates_cmd import (
    cmd_templates_list, cmd_templates_show, cmd_templates_apply,
    cmd_templates_create, cmd_templates_edit, cmd_templates_delete,
)
from .cli_ext.metrics_cmd import cmd_metrics_show, cmd_metrics_reset, cmd_metrics_export, cmd_metrics_cost
from .cli_ext.llm_providers_cmd import (
    cmd_llm_providers_list, cmd_llm_providers_show,
    cmd_llm_providers_add, cmd_llm_providers_remove,
    cmd_llm_providers_test, cmd_llm_providers_set_default,
    cmd_llm_providers_rotate_key,
)
from .cli_ext.health_cmd import cmd_health
from .cli_ext.content_health_cmd import cmd_content_health
from .cli_ext.quality_cmd import (
    cmd_quality_score, cmd_quality_config_show, cmd_quality_config_set,
)
from .cli_ext.vision_cmd import cmd_vision_list, cmd_vision_extract
from .cli_ext.serve import cmd_serve, cmd_serve_stop, cmd_serve_status
from .cli_ext.research_cmd import add_research_subcommands
from .cli_ext.relations_cmd import (
    cmd_relations_list, cmd_relations_backlinks, cmd_relations_neighbors,
    cmd_relations_path, cmd_relations_types, cmd_relations_add_type,
)
from .cli_ext.fields_cmd import cmd_fields_validate, cmd_tags_validate
from .cli_ext.heat_cmd import (
    cmd_heat_show, cmd_heat_top, cmd_heat_cold, cmd_heat_decay,
    cmd_heat_zombies, cmd_heat_restore, cmd_heat_archive,
)
from .cli_ext.cache_cmd import cmd_cache_status, cmd_cache_cleanup
from .cli_ext.batch_cmd import add_batch_subcommands
from .cli_ext.scripts_cmd import add_scripts_subcommands
from .cli_ext.wiki_polish_cmd import (
    cmd_stubs_list, cmd_stubs_promote, cmd_dedup_auto,
    cmd_lint_cache_clear, cmd_lint,
)
from .cli_ext.auth_token_cmd import add_auth_token_parser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

def _override_config_dir_from_env():
    """Allow RUFLO_CONFIG_DIR env var to override OS-standard config dir (for tests)."""
    from src.config import settings
    env_dir = settings().config_dir
    if env_dir:
        # Monkey-patch at import time
        import src.project.paths as paths
        paths._OVERRIDE_CONFIG_DIR = Path(env_dir)


def _run_mcp():
    """Start the stdio MCP server (delegates to src.mcp_server.main.main)."""
    from .mcp_server.main import main as mcp_main
    asyncio.run(mcp_main())


def main():
    _override_config_dir_from_env()
    auto_register_on_first_run()  # idempotent

    parser = argparse.ArgumentParser(description="ruflo-kb 多Agent知识库")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # Project subcommand
    p_project = subparsers.add_parser("project", help="Manage projects")
    p_project_sub = p_project.add_subparsers(dest="project_command")

    p_init = p_project_sub.add_parser("init", help="Initialize new project")
    p_init.add_argument("path", help="Project root directory")
    p_init.add_argument("--name", help="Project name (default: path basename)")
    p_init.add_argument("--template", default=None, help="Template name (e.g. research, reading, personal, business, general)")
    p_init.set_defaults(func=cmd_project_init)

    p_list = p_project_sub.add_parser("list", help="List registered projects")
    p_list.set_defaults(func=cmd_project_list)

    p_info = p_project_sub.add_parser("info", help="Show project metadata")
    p_info.add_argument("id_or_name", help="Project UUID or name")
    p_info.set_defaults(func=cmd_project_info)

    p_current = p_project_sub.add_parser("current", help="Show current project")
    p_current.set_defaults(func=cmd_project_current)

    p_select = p_project_sub.add_parser("select", help="Set last_project pointer")
    p_select.add_argument("id_or_name", help="Project UUID or name")
    p_select.set_defaults(func=cmd_project_select)

    p_import = p_project_sub.add_parser("import", help="Import existing KB")
    p_import.add_argument("path", help="Path to existing KB root")
    p_import.add_argument("--name", help="Override project name")
    p_import.set_defaults(func=cmd_project_import)

    p_forget = p_project_sub.add_parser("forget", help="Remove project from registry")
    p_forget.add_argument("id_or_name", help="Project UUID or name")
    p_forget.add_argument("--delete-data", action="store_true", help="Also delete files")
    p_forget.set_defaults(func=cmd_project_forget)

    p_rename = p_project_sub.add_parser("rename", help="Rename a project")
    p_rename.add_argument("id_or_name", help="Current project UUID or name")
    p_rename.add_argument("new_name", help="New project name")
    p_rename.set_defaults(func=cmd_project_rename)

    p_discover = p_project_sub.add_parser("discover", help="Auto-discover existing KBs")
    p_discover.set_defaults(func=cmd_project_discover)

    p_set_provider = p_project_sub.add_parser("set-provider", help="Set LLM provider for a project")
    p_set_provider.add_argument("id_or_name", help="Project UUID or name")
    p_set_provider.add_argument("provider_name", help="LLM provider name (e.g. ollama, minimax)")
    p_set_provider.set_defaults(func=cmd_project_set_provider)

    p_set_model = p_project_sub.add_parser("set-model", help="Set LLM model for a project")
    p_set_model.add_argument("id_or_name", help="Project UUID or name")
    p_set_model.add_argument("model_name", help="LLM model name (e.g. qwen3.5-9b-gemini:latest)")
    p_set_model.set_defaults(func=cmd_project_set_model)

    # Schema subcommand
    p_schema = subparsers.add_parser("schema", help="Schema management")
    p_schema_sub = p_schema.add_subparsers(dest="schema_command")

    p_slist = p_schema_sub.add_parser("list", help="List schemas + migrations")
    p_slist.set_defaults(func=cmd_schema_list)

    p_sdiff = p_schema_sub.add_parser("diff", help="Show schema version differences")
    p_sdiff.add_argument("schema", help="Schema name")
    p_sdiff.add_argument("from_v", help="From version (e.g. v2.0)")
    p_sdiff.add_argument("to_v", help="To version (e.g. v2.1)")
    p_sdiff.set_defaults(func=cmd_schema_diff)

    p_sup = p_schema_sub.add_parser("upgrade", help="Upgrade schema")
    p_sup.add_argument("--to", required=True, help="Target version")
    p_sup.add_argument("--preview", action="store_true", help="Preview only")
    p_sup.set_defaults(func=cmd_schema_upgrade)

    p_sdown = p_schema_sub.add_parser("downgrade", help="Downgrade schema")
    p_sdown.add_argument("--to", required=True, help="Target version")
    p_sdown.add_argument("--preview", action="store_true")
    p_sdown.set_defaults(func=cmd_schema_downgrade)

    p_sbackup = p_schema_sub.add_parser("backup", help="List or restore backups")
    p_sbackup.add_argument("action", choices=["list", "restore"], help="Action")
    p_sbackup.add_argument("--name", help="Backup name (for restore)")
    p_sbackup.set_defaults(func=cmd_schema_backup)

    # Atomic context status
    p_atomic = subparsers.add_parser("atomic", help="Atomic context status")
    p_atomic.set_defaults(func=cmd_atomic_status)

    # Token budget utilities
    p_budget = subparsers.add_parser("budget", help="Token budget utilities")
    p_budget_sub = p_budget.add_subparsers(dest="budget_command")

    p_bestimate = p_budget_sub.add_parser("estimate", help="Estimate tokens for file")
    p_bestimate.add_argument("path", help="File path")
    p_bestimate.set_defaults(func=cmd_budget_estimate)

    p_bcheck = p_budget_sub.add_parser("check", help="Check if file fits in model")
    p_bcheck.add_argument("path", help="File path")
    p_bcheck.add_argument("--model", default="gpt-4o-mini", help="Model name")
    p_bcheck.set_defaults(func=cmd_budget_check)

    # Completions
    p_comp = subparsers.add_parser("completions", help="Manage shell completions")
    p_comp_sub = p_comp.add_subparsers(dest="completions_action")
    p_comp_inst = p_comp_sub.add_parser("install")
    p_comp_inst.add_argument("shell", choices=["bash", "zsh", "fish"])
    p_comp_inst.set_defaults(func=cmd_completions)
    p_comp_show = p_comp_sub.add_parser("show")
    p_comp_show.add_argument("shell", choices=["bash", "zsh"])
    p_comp_show.set_defaults(func=cmd_completions)
    p_comp_pw = p_comp_sub.add_parser("print-words")
    p_comp_pw.set_defaults(func=cmd_completions)

    # Templates
    p_tmpl = subparsers.add_parser("templates", help="Project templates")
    p_tmpl_sub = p_tmpl.add_subparsers(dest="templates_action")
    p_tmpl_list = p_tmpl_sub.add_parser("list")
    p_tmpl_list.set_defaults(func=cmd_templates_list)
    p_tmpl_show = p_tmpl_sub.add_parser("show")
    p_tmpl_show.add_argument("name", help="Template name")
    p_tmpl_show.set_defaults(func=cmd_templates_show)
    p_tmpl_apply = p_tmpl_sub.add_parser("apply")
    p_tmpl_apply.add_argument("name", help="Template name")
    p_tmpl_apply.add_argument("--project", help="Project to apply to (UUID/name)")
    p_tmpl_apply.add_argument("--force", action="store_true", help="Overwrite existing template files")
    p_tmpl_apply.set_defaults(func=cmd_templates_apply)
    p_tmpl_create = p_tmpl_sub.add_parser("create")
    p_tmpl_create.add_argument("name")
    p_tmpl_create.add_argument("--from", dest="source", default="general")
    p_tmpl_create.add_argument("--description")
    p_tmpl_create.add_argument("--icon")
    p_tmpl_create.set_defaults(func=cmd_templates_create)
    p_tmpl_edit = p_tmpl_sub.add_parser("edit")
    p_tmpl_edit.add_argument("name")
    p_tmpl_edit.add_argument("--description")
    p_tmpl_edit.add_argument("--icon")
    p_tmpl_edit.set_defaults(func=cmd_templates_edit)
    p_tmpl_delete = p_tmpl_sub.add_parser("delete")
    p_tmpl_delete.add_argument("name")
    p_tmpl_delete.set_defaults(func=cmd_templates_delete)

    # Metrics
    p_metrics = subparsers.add_parser("metrics", help="Metrics utilities")
    p_metrics_sub = p_metrics.add_subparsers(dest="metrics_command")
    p_mshow = p_metrics_sub.add_parser("show")
    p_mshow.set_defaults(func=cmd_metrics_show)
    p_mreset = p_metrics_sub.add_parser("reset")
    p_mreset.set_defaults(func=cmd_metrics_reset)
    p_mexport = p_metrics_sub.add_parser("export")
    p_mexport.add_argument("path", help="Output JSON path")
    p_mexport.set_defaults(func=cmd_metrics_export)
    p_mcost = p_metrics_sub.add_parser("cost")
    p_mcost.set_defaults(func=cmd_metrics_cost)

    # LLM providers
    p_llm = subparsers.add_parser("llm-providers", help="Manage LLM providers")
    p_llm_sub = p_llm.add_subparsers(dest="llm_providers_command")
    p_llm_list = p_llm_sub.add_parser("list")
    p_llm_list.set_defaults(func=cmd_llm_providers_list)
    p_llm_show = p_llm_sub.add_parser("show")
    p_llm_show.add_argument("name")
    p_llm_show.set_defaults(func=cmd_llm_providers_show)
    p_llm_add = p_llm_sub.add_parser("add")
    p_llm_add.add_argument("name")
    p_llm_add.add_argument("type", choices=["openai", "anthropic", "ollama", "openai-compatible"])
    p_llm_add.add_argument("--base-url", default="")
    p_llm_add.add_argument("--api-key", default="")
    p_llm_add.add_argument("--model", default="")
    p_llm_add.set_defaults(func=cmd_llm_providers_add)
    p_llm_rm = p_llm_sub.add_parser("remove")
    p_llm_rm.add_argument("name")
    p_llm_rm.set_defaults(func=cmd_llm_providers_remove)
    p_llm_test = p_llm_sub.add_parser("test")
    p_llm_test.add_argument("name")
    p_llm_test.set_defaults(func=cmd_llm_providers_test)
    p_llm_sd = p_llm_sub.add_parser("set-default")
    p_llm_sd.add_argument("name")
    p_llm_sd.set_defaults(func=cmd_llm_providers_set_default)
    p_llm_rot = p_llm_sub.add_parser("rotate-key", help="Replace a provider's API key (R15)")
    p_llm_rot.add_argument("name")
    p_llm_rot.add_argument("--api-key", default="")
    p_llm_rot.set_defaults(func=cmd_llm_providers_rotate_key)

    # Health
    p_health = subparsers.add_parser("health", help="Run wiki health checks (H1/H2/H4)")
    p_health.add_argument("--only", nargs="*", help="Run only these checks")
    p_health.add_argument("--skip", nargs="*", help="Skip these checks")
    p_health.add_argument("--strict", action="store_true", help="Exit 1 on error")
    p_health.add_argument("--json", action="store_true", help="JSON output")
    p_health.add_argument("--project", help="Project path (default: cwd)")
    p_health.set_defaults(func=cmd_health)

    p_content_health = subparsers.add_parser(
        "content-health", help="Show read-only aggregate wiki content health"
    )
    p_content_health.add_argument("--json", action="store_true", help="JSON output")
    p_content_health.add_argument("--project", help="Project path (default: cwd)")
    p_content_health.set_defaults(func=cmd_content_health)

    # Quality
    p_quality = subparsers.add_parser("quality", help="Quality gate")
    p_quality_sub = p_quality.add_subparsers(dest="quality_command")
    p_qscore = p_quality_sub.add_parser("score", help="Score a markdown page")
    p_qscore.add_argument("path", help="Path to .md file")
    p_qscore.set_defaults(func=cmd_quality_score)
    p_qconfig = p_quality_sub.add_parser("config", help="Quality config")
    p_qconfig_sub = p_qconfig.add_subparsers(dest="quality_config_command")
    p_qcshow = p_qconfig_sub.add_parser("show")
    p_qcshow.set_defaults(func=cmd_quality_config_show)
    p_qcset = p_qconfig_sub.add_parser("set")
    p_qcset.add_argument("key")
    p_qcset.add_argument("value")
    p_qcset.add_argument("--config-root", default=None,
                         help="Override config root (default: cwd)")
    p_qcset.set_defaults(func=cmd_quality_config_set)

    # Vision
    p_vision = subparsers.add_parser("vision", help="Vision/image utilities")
    p_vision_sub = p_vision.add_subparsers(dest="vision_command")
    p_vlist = p_vision_sub.add_parser("list")
    p_vlist.add_argument("--project-root", default=None)
    p_vlist.set_defaults(func=cmd_vision_list)
    p_vextract = p_vision_sub.add_parser("extract", help="Extract + caption images from PDF")
    p_vextract.add_argument("path", help="Path to PDF")
    p_vextract.add_argument("--task-id", default=None)
    p_vextract.add_argument("--project-root", default=None)
    p_vextract.add_argument("--provider", default=None)
    p_vextract.add_argument("--model", default=None)
    p_vextract.set_defaults(func=cmd_vision_extract)

    # Wiki page templates (Plan 25 v1 follow-up)
    from .cli_ext.wiki_templates_cmd import add_wiki_templates_parser
    add_wiki_templates_parser(subparsers)

    # v2.4 migration: rename kb-*.md source pages to {stem}-{8hex}.md
    from .cli_ext.migrate_source_slugs_cmd import add_wiki_migrate_source_slugs_parser
    add_wiki_migrate_source_slugs_parser(subparsers)

    # v2.5 strict-scope cleanup
    from .cli_ext.wiki_cleanup_v1_cmd import add_wiki_cleanup_v1_parser
    add_wiki_cleanup_v1_parser(subparsers)

    # Serve (HTTP API server)
    p_serve = subparsers.add_parser("serve", help="Start HTTP API server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=19828)
    p_serve.add_argument("--daemon", action="store_true")
    p_serve.add_argument("--workers", type=int, default=1,
                         help="Uvicorn workers (only 1 is supported — R6)")
    p_serve.add_argument("--project-root", default=None,
                         help="Explicit project root (required — R14)")
    p_serve.set_defaults(func=cmd_serve)
    p_serve_stop = subparsers.add_parser("serve-stop", help="Stop daemon server")
    p_serve_stop.set_defaults(func=cmd_serve_stop)
    p_serve_status = subparsers.add_parser("serve-status", help="Check daemon status")
    p_serve_status.set_defaults(func=cmd_serve_status)

    # R1: bearer-token management for the HTTP management surface
    add_auth_token_parser(subparsers)

    # MCP (stdio Model Context Protocol server)
    p_mcp = subparsers.add_parser("mcp", help="Start stdio MCP server")
    p_mcp.set_defaults(func=lambda args: asyncio.run(_run_mcp()))

    # Deep Research (research {run,list,show})
    add_research_subcommands(subparsers)

    # Batch runner (batch {run,plan,...} — P1-A 3d + 遗留脚本收编)
    add_batch_subcommands(subparsers)

    # Legacy script groups (migrate / audit / util — 遗留脚本收编)
    add_scripts_subcommands(subparsers)

    # Relations subcommand
    p_relations = subparsers.add_parser("relations", help="Manage wiki relations")
    p_rel_sub = p_relations.add_subparsers(dest="relations_command", required=True)

    p_r_list = p_rel_sub.add_parser("list", help="List relations of a page")
    p_r_list.add_argument("page_id")
    p_r_list.add_argument("--project", required=True)
    p_r_list.set_defaults(func=cmd_relations_list)

    p_r_bl = p_rel_sub.add_parser("backlinks", help="Find backlinks to a page")
    p_r_bl.add_argument("page_id")
    p_r_bl.add_argument("--project", required=True)
    p_r_bl.set_defaults(func=cmd_relations_backlinks)

    p_r_n = p_rel_sub.add_parser("neighbors", help="Find neighbors within N hops")
    p_r_n.add_argument("page_id")
    p_r_n.add_argument("--depth", type=int, default=1)
    p_r_n.add_argument("--project", required=True)
    p_r_n.set_defaults(func=cmd_relations_neighbors)

    p_r_path = p_rel_sub.add_parser("path", help="Find shortest path between pages")
    p_r_path.add_argument("from_id")
    p_r_path.add_argument("to_id")
    p_r_path.add_argument("--project", required=True)
    p_r_path.set_defaults(func=cmd_relations_path)

    p_r_types = p_rel_sub.add_parser("types", help="List known relation types")
    p_r_types.set_defaults(func=cmd_relations_types)

    p_r_add = p_rel_sub.add_parser("add-type", help="Register a user-defined relation type")
    p_r_add.add_argument("name")
    p_r_add.set_defaults(func=cmd_relations_add_type)

    # Fields validation
    p_fields = subparsers.add_parser("fields", help="Validate wiki fields")
    p_fields_sub = p_fields.add_subparsers(dest="fields_command", required=True)
    p_fvalidate = p_fields_sub.add_parser("validate")
    p_fvalidate.add_argument("path")
    p_fvalidate.add_argument("--project")
    p_fvalidate.set_defaults(func=cmd_fields_validate)

    # Tags validation
    p_tags = subparsers.add_parser("tags", help="Validate tags")
    p_tags_sub = p_tags.add_subparsers(dest="tags_command", required=True)
    p_tvalidate = p_tags_sub.add_parser("validate")
    p_tvalidate.add_argument("page_path", nargs="?")
    p_tvalidate.add_argument("--all", action="store_true")
    p_tvalidate.add_argument("--project")
    p_tvalidate.set_defaults(func=cmd_tags_validate)

    # Heat subcommand
    p_heat = subparsers.add_parser("heat", help="Wiki heat decay + zombie detection")
    p_heat_sub = p_heat.add_subparsers(dest="heat_command", required=True)

    p_hshow = p_heat_sub.add_parser("show")
    p_hshow.add_argument("page_id")
    p_hshow.add_argument("--project")
    p_hshow.set_defaults(func=cmd_heat_show)

    p_htop = p_heat_sub.add_parser("top")
    p_htop.add_argument("--limit", type=int, default=10)
    p_htop.add_argument("--project")
    p_htop.set_defaults(func=cmd_heat_top)

    p_hcold = p_heat_sub.add_parser("cold")
    p_hcold.add_argument("--limit", type=int, default=10)
    p_hcold.add_argument("--project")
    p_hcold.set_defaults(func=cmd_heat_cold)

    p_hdecay = p_heat_sub.add_parser("decay")
    p_hdecay.add_argument("--dry-run", action="store_true")
    p_hdecay.add_argument("--project")
    p_hdecay.set_defaults(func=cmd_heat_decay)

    p_hzombies = p_heat_sub.add_parser("zombies")
    p_hzombies.add_argument("--project")
    p_hzombies.set_defaults(func=cmd_heat_zombies)

    p_hrestore = p_heat_sub.add_parser("restore")
    p_hrestore.add_argument("page_id")
    p_hrestore.add_argument("--project")
    p_hrestore.set_defaults(func=cmd_heat_restore)

    p_harchive = p_heat_sub.add_parser("archive")
    p_harchive.add_argument("page_id")
    p_harchive.add_argument("--project")
    p_harchive.set_defaults(func=cmd_heat_archive)

    # Cache management
    p_cache = subparsers.add_parser("cache", help="Cache management (status + cleanup)")
    p_cache_sub = p_cache.add_subparsers(dest="cache_command", required=True)

    p_cstatus = p_cache_sub.add_parser("status", help="Show cache sizes and staleness")
    p_cstatus.add_argument("--project")
    p_cstatus.set_defaults(func=cmd_cache_status)

    p_ccleanup = p_cache_sub.add_parser("cleanup", help="Clean up stale cache entries")
    p_ccleanup.add_argument("--project")
    p_ccleanup.add_argument("--dry-run", action="store_true", help="Show what would be cleaned")
    p_ccleanup.set_defaults(func=cmd_cache_cleanup)

    # Wiki polish commands
    p_stubs = subparsers.add_parser("stubs", help="Manage wiki stub pages")
    p_stubs_sub = p_stubs.add_subparsers(dest="stubs_command", required=True)
    p_slist = p_stubs_sub.add_parser("list")
    p_slist.add_argument("--project")
    p_slist.set_defaults(func=cmd_stubs_list)
    p_spromote = p_stubs_sub.add_parser("promote")
    p_spromote.add_argument("--project")
    p_spromote.set_defaults(func=cmd_stubs_promote)
    p_dedup = subparsers.add_parser("dedup", help="Deduplicate wiki pages")
    p_dedup_sub = p_dedup.add_subparsers(dest="dedup_command", required=True)
    p_dauto = p_dedup_sub.add_parser("auto")
    p_dauto.add_argument("--threshold", default="high", choices=["high", "medium", "low"])
    p_dauto.add_argument("--project")
    p_dauto.set_defaults(func=cmd_dedup_auto)
    p_lint = subparsers.add_parser("lint", help="Run wiki lint with caching")
    p_lint.add_argument("--cache-ttl", type=int, default=None)
    p_lint.add_argument("--no-cache", action="store_true")
    p_lint.add_argument("--project")
    p_lint.set_defaults(func=cmd_lint)
    p_lcache = subparsers.add_parser("lint-cache-clear", help="Clear lint cache")
    p_lcache.add_argument("--project")
    p_lcache.set_defaults(func=cmd_lint_cache_clear)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)

if __name__ == "__main__":
    main()

# ruflo-kb/src/cli.py
"""
ruflo-kb CLI 入口

用法:
    python -m src.cli init          # 初始化知识库目录
    python -m src.cli status         # 查看队列状态
    python -m src.cli ingest <url>  # 采集URL
    python -m src.cli search <query> # 搜索
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from .knowledge_base import ensure_knowledge_base, get_knowledge_base_paths
from .queue.queue import get_queue_status, pause_queue, resume_queue, enqueue_task
from .orchestrator.orchestrator import get_orchestrator
from .types import SourceType
from .llm import create_embedding_provider, create_llm_provider
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
from .cli_ext.templates_cmd import cmd_templates_list, cmd_templates_show, cmd_templates_apply
from .cli_ext.metrics_cmd import cmd_metrics_show, cmd_metrics_reset, cmd_metrics_export, cmd_metrics_cost
from .cli_ext.llm_providers_cmd import (
    cmd_llm_providers_list, cmd_llm_providers_show,
    cmd_llm_providers_add, cmd_llm_providers_remove,
    cmd_llm_providers_test, cmd_llm_providers_set_default,
)
from .cli_ext.health_cmd import cmd_health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

def cmd_init(args):
    """初始化知识库目录"""
    paths = ensure_knowledge_base(args.path)
    print(f"知识库目录已初始化:")
    print(f"  根目录: {paths.base}")
    print(f"  Inbox: {paths.inbox}")
    print(f"  Notes: {paths.notes}")
    print(f"  Knowledge: {paths.knowledge}")
    print(f"  Index: {paths.index}")

def cmd_status(args):
    """查看队列状态"""
    status = get_queue_status()
    print("队列状态:")
    for key, value in status.items():
        print(f"  {key}: {value}")

def cmd_pause(args):
    """暂停队列"""
    pause_queue()
    print("队列已暂停")

def cmd_resume(args):
    """恢复队列"""
    resume_queue()
    print("队列已恢复")

def cmd_ingest(args):
    """采集内容"""
    orchestrator = get_orchestrator()
    result = orchestrator.process(args.url)

    if result.get("status") == "ignored":
        print(f"重复提交，已忽略: {args.url}")
    elif result.get("status") == "queued":
        print(f"已加入队列: {result.get('task_id')}")
    elif result.get("status") == "searching":
        print(f"搜索模式不支持直接采集，请使用 ? <query> 进行搜索")
    else:
        print(f"未知状态: {result}")

def cmd_search(args):
    """搜索内容"""
    orchestrator = get_orchestrator()
    result = orchestrator.process(f"?{args.query}")

    if result.get("status") == "searching":
        print(f"搜索中: {result.get('query')}")
    else:
        print(f"状态: {result}")

def cmd_configure(args):
    """配置 LLM Provider"""
    if args.openai_key:
        import os
        os.environ["OPENAI_API_KEY"] = args.openai_key
        print(f"已设置 OpenAI API Key")

    if args.provider == "openai":
        print(f"使用 OpenAI Provider")
    elif args.provider == "anthropic":
        print(f"使用 Anthropic Provider")

def _override_config_dir_from_env():
    """Allow RUFLO_CONFIG_DIR env var to override OS-standard config dir (for tests)."""
    env_dir = os.environ.get("RUFLO_CONFIG_DIR")
    if env_dir:
        # Monkey-patch at import time
        import src.project.paths as paths
        paths._OVERRIDE_CONFIG_DIR = Path(env_dir)


def main():
    _override_config_dir_from_env()
    auto_register_on_first_run()  # idempotent

    parser = argparse.ArgumentParser(description="ruflo-kb 多Agent知识库")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # init
    p_init = subparsers.add_parser("init", help="初始化知识库目录")
    p_init.add_argument("--path", default=".", help="知识库根目录路径")
    p_init.set_defaults(func=cmd_init)

    # status
    p_status = subparsers.add_parser("status", help="查看队列状态")
    p_status.set_defaults(func=cmd_status)

    # pause
    p_pause = subparsers.add_parser("pause", help="暂停队列")
    p_pause.set_defaults(func=cmd_pause)

    # resume
    p_resume = subparsers.add_parser("resume", help="恢复队列")
    p_resume.set_defaults(func=cmd_resume)

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="采集URL或文件")
    p_ingest.add_argument("url", help="URL或文件路径")
    p_ingest.set_defaults(func=cmd_ingest)

    # search
    p_search = subparsers.add_parser("search", help="搜索知识库")
    p_search.add_argument("query", help="搜索关键词")
    p_search.set_defaults(func=cmd_search)

    # configure
    p_config = subparsers.add_parser("configure", help="配置 LLM")
    p_config.add_argument("--provider", default="openai", choices=["openai", "anthropic"], help="LLM Provider")
    p_config.add_argument("--openai-key", help="OpenAI API Key")
    p_config.set_defaults(func=cmd_configure)

    # Project subcommand
    p_project = subparsers.add_parser("project", help="Manage projects")
    p_project_sub = p_project.add_subparsers(dest="project_command")

    p_init = p_project_sub.add_parser("init", help="Initialize new project")
    p_init.add_argument("path", help="Project root directory")
    p_init.add_argument("--name", help="Project name (default: path basename)")
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
    p_tmpl_apply.set_defaults(func=cmd_templates_apply)

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
    p_llm_add.add_argument("type", choices=["openai", "anthropic", "ollama"])
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

    # Health
    p_health = subparsers.add_parser("health", help="Run wiki health checks (H1/H2/H4)")
    p_health.add_argument("--only", nargs="*", help="Run only these checks")
    p_health.add_argument("--skip", nargs="*", help="Skip these checks")
    p_health.add_argument("--strict", action="store_true", help="Exit 1 on error")
    p_health.add_argument("--json", action="store_true", help="JSON output")
    p_health.add_argument("--project", help="Project path (default: cwd)")
    p_health.set_defaults(func=cmd_health)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)

if __name__ == "__main__":
    main()

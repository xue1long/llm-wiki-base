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
import sys
from pathlib import Path

from .knowledge_base import ensure_knowledge_base, get_knowledge_base_paths
from .queue.queue import get_queue_status, pause_queue, resume_queue, enqueue_task
from .orchestrator.orchestrator import get_orchestrator
from .types import SourceType
from .llm import create_embedding_provider, create_llm_provider
from .cli_ext.project_cmd import (
    cmd_project_current,
    cmd_project_info,
    cmd_project_init,
    cmd_project_list,
    cmd_project_select,
)

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

def main():
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

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)

if __name__ == "__main__":
    main()

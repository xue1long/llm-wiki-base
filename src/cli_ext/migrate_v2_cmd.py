from __future__ import annotations
import json
from src.wiki.migrate.v2_full import migrate_v2, resolve_project

def cmd_migrate_v2(args):
    target=resolve_project(args.project)
    result=migrate_v2(target,args.v2_path,run_id=args.run_id,apply=args.apply,resume=args.resume,rollback=args.rollback)
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str) if args.json else result)

def add_migrate_v2_parser(subparsers):
    parser=subparsers.add_parser("migrate-v2",help="Migrate LLM_Knowledge_base_v2 into a project")
    parser.add_argument("--project",required=True,help="target project UUID")
    parser.add_argument("--v2-path",required=True,help="absolute v2 source path")
    parser.add_argument("--run-id")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--rollback",action="store_true")
    parser.add_argument("--json",action="store_true")
    parser.set_defaults(func=cmd_migrate_v2)

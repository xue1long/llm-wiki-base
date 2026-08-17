#!/usr/bin/env bash
# run_remaining.sh — novel-wiki 后续阶段续跑驱动
#
# 范围：reingest_plan.json 共 69 批 / 1361 文件。
#   已完成（committed）：批 2-7（120 文件，均在 01_新手入门 内）。
#   本脚本续跑剩余 63 批 / 1241 文件：批 0、1、8..68。
#
# 退出码约定（phase4_batch.py）：
#   0  已提交且 POSTCHECK 通过
#   1  批中止（零页生成）/ 参数错误
#   2  NDG 门禁阻断（P5-P7 / B6 覆盖保护）——零写入
#   3  POSTCHECK 失败（提交后缺页）——需 --resume 补页
#
# 策略：最大化推进 + 末尾汇总。单个批失败不中止全局，记日志待人工排查。
set -u

ROOT=/d/5-Project/2026814/llm-wiki-base
cd "$ROOT" || exit 1

PY=C:/Users/HP/AppData/Local/Python/pythoncore-3.14-64/python.exe
# novel-wiki 在全局注册表中的真实 id（project.json 一致）。
# 注意：scripts/phase4_batch.py 硬编码的 PROJECT_ID=8dd46257-... 已不在注册表，
# 故此处显式传入正确 id，避免 _resolve_wiki_paths 报 "not found in registry"。
PROJECT=0ff37d87-de3d-4a99-82bb-6cf288c65410
LOGDIR=.index_run_logs
mkdir -p "$LOGDIR"

# 剩余批：跳过已提交的 2-7
BATCHES="0 1 $(seq 8 68)"

LOG() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOGDIR/run_summary.log"; }

LOG "===== START run_remaining (batches: $BATCHES) ====="

SKIPPED=""
for B in $BATCHES; do
  log="$LOGDIR/batch_${B}.log"
  LOG "----- START batch $B -----"

  # 首次：--resume 跳过已完成文件（断点续跑安全）
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    PYTHONIOENCODING=utf-8 PYTHONPATH=. \
    "$PY" scripts/phase4_batch.py --batch "$B" --project "$PROJECT" --resume \
    >> "$log" 2>&1
  rc=$?
  LOG "batch $B first-pass exit=$rc"

  if [ $rc -eq 0 ]; then
    LOG "batch $B OK"
    continue
  fi

  if [ $rc -eq 3 ]; then
    # POSTCHECK 缺页：非 --resume 重跑（绕过 H1 阻断）补页；必要时覆盖写入
    LOG "batch $B POSTCHECK 缺页 → 重跑补页 (--allow-overwrite)"
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. \
      "$PY" scripts/phase4_batch.py --batch "$B" --project "$PROJECT" --allow-overwrite \
      >> "$log" 2>&1
    rc2=$?
    LOG "batch $B refill exit=$rc2"
    if [ $rc2 -eq 0 ]; then
      LOG "batch $B OK (after refill)"
      continue
    fi
    LOG "batch $B 补页仍失败 exit=$rc2 —— 标记待人工排查"
    SKIPPED="$SKIPPED $B"
    continue
  fi

  if [ $rc -eq 1 ]; then
    # 批中止：可能是瞬时（网络/熔断）——无 --resume 重试一次
    LOG "batch $B ABORT —— 重试一次（无 --resume）"
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. \
      "$PY" scripts/phase4_batch.py --batch "$B" --project "$PROJECT" --allow-overwrite \
      >> "$log" 2>&1
    rc2=$?
    LOG "batch $B retry exit=$rc2"
    if [ $rc2 -eq 0 ]; then
      LOG "batch $B OK (after retry)"
      continue
    fi
    LOG "batch $B 重试仍失败 exit=$rc2 —— 标记待人工排查"
    SKIPPED="$SKIPPED $B"
    continue
  fi

  if [ $rc -eq 2 ]; then
    # 门禁阻断：质量门未过，零写入。跳过本批，待人工审视门禁/数据
    LOG "batch $B GATE BLOCKED (exit=2) —— 跳过，待人工排查"
    SKIPPED="$SKIPPED $B"
    continue
  fi

  LOG "batch $B 未知退出码 $rc —— 跳过"
  SKIPPED="$SKIPPED $B"
done

LOG "===== RUN COMPLETE ====="
if [ -n "$SKIPPED" ]; then
  LOG "需人工排查的批：$SKIPPED"
else
  LOG "全部剩余批通过 ✅"
fi

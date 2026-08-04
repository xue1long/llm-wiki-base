# ruflo-kb/src/orchestrator/audit_hard.py
import yaml
import re
from pathlib import Path
from dataclasses import dataclass

@dataclass
class HardAuditResult:
    passed: bool
    reasons: list[str]

# 硬规则阈值
QUALITY_SCORE_THRESHOLD = 0.6

def run_hard_audit(note_path: str) -> HardAuditResult:
    """
    硬规则审核（Orchestrator 执行）
    仅检查：文件存在性、非空、必填字段、quality_score
    """
    reasons = []
    passed = True

    # 规则1: 文件存在性
    path = Path(note_path)
    if not path.exists():
        return HardAuditResult(passed=False, reasons=[f"文件不存在: {note_path}"])

    # 规则2: 文件非空
    if path.stat().st_size == 0:
        reasons.append("文件为空")
        passed = False

    # 规则3: 读取 Frontmatter
    try:
        content = path.read_text(encoding="utf-8")
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            fm = yaml.safe_load(fm_text)

            # 规则4: 必填字段
            if not fm.get("title"):
                reasons.append("缺少 title 字段")
                passed = False
            if not fm.get("source"):
                reasons.append("缺少 source 字段")
                passed = False

            # 规则5: quality_score 阈值
            quality_score = fm.get("quality_score")
            if quality_score is not None:
                if quality_score < QUALITY_SCORE_THRESHOLD:
                    reasons.append(f"quality_score ({quality_score}) < 阈值 ({QUALITY_SCORE_THRESHOLD})")
                    passed = False
        else:
            reasons.append("缺少 Frontmatter")
            passed = False
    except Exception as e:
        reasons.append(f"读取失败: {e}")
        passed = False

    return HardAuditResult(passed=passed, reasons=reasons)

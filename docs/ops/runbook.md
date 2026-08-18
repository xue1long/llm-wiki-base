# ruflo-kb 运维 Runbook（R12 告警 + R13 版本/备份/回滚）

> 适用范围：受控单机、单进程、单 worker、本机文件系统部署。
> 所有命令从仓库根目录运行；`<project>` 是项目 id（`ruflo project list` 查看）。

---

## 1. 部署形态（硬约束）

- 单进程单 worker：`serve --workers 2` 会被拒绝（R6）。
- 非回环绑定必须配置 Bearer Token（R1）：
  ```bash
  python -m src.cli auth-token generate
  python -m src.cli serve --host 0.0.0.0 --port 19828 --project-root /path/to/kb
  ```
- 回环部署无需 Token，但同样要求 `--project-root`（R14，拒绝 CWD 猜测）。
- 同一项目目录禁止第二个服务实例（`.llm-wiki/server.lock`）。

## 2. 健康与就绪

| 端点 | 语义 | 说明 |
|---|---|---|
| `GET /health` | liveness | 进程存活即 200，永远 `ok: true` |
| `GET /ready` | readiness | 分项 queue/wiki/vector/provider，200/503 |
| `GET /metrics` | Prometheus | 指标文本格式 |

`/ready` 组件状态：
- `ok` — 组件可用
- `degraded` — 可用但有损（如 keyword-only 检索），不摘除
- `error` — 硬故障，503

## 3. 告警规则（R12）

指标端点：`GET /metrics`（Prometheus 文本）。以下四条为 P1 告警契约：

| 告警 | 指标 | 阈值 | 止损动作 |
|---|---|---|---|
| 任务死信 | `ruflo_dead_letter_total` | 5 分钟内 > 0 | 查 `ruflo batch diagnose-gate`；死信任务源重试 |
| 队列积压 | `ruflo_queue_backlog{status="pending"}` | > 50 | 查 Provider 健康、磁盘；`ruflo serve-status` |
| Provider 连续失败 | `ruflo_provider_failure_total` | 3 次连续（circuit open） | `ruflo llm-providers test <name>`；检查网络/Key |
| 写失败 | `ruflo_write_failure_total` | 10 分钟内 > 0 | 查磁盘空间/权限；`ruflo vector status` 检查 pending |

示例 PromQL：
```
sum(rate(ruflo_dead_letter_total[5m])) > 0
ruflo_queue_backlog{status="pending"} > 50
```

## 4. 关联 ID（R12）

HTTP 请求 → Queue 任务 → Pipeline → Provider → Writer 的日志通过
`request_id` / `task_id` / `project_id` 三个字段关联（`src/lib/correlation.py`）。
- HTTP 入口自动生成 `request_id`（或接受 `X-Request-Id` 头）。
- 排查单任务：先拿 `task_id`，再 grep 日志中的该 id。

## 5. 版本（R13）

- 唯一版本源：`pyproject.toml` 的 `version`（当前 `2.0.0`）。
- `GET /health` 返回同一版本（R13 统一后）。
- 版本判断一律以 `python -m src.cli --version`（如有）或 pyproject 为准。

## 6. 备份 → 升级 → smoke → 回滚 → 向量重建（R13）

### 6.1 备份

```bash
# 备份 Wiki（事实源）+ 项目元数据 + 队列
tar -czf backup-$(date +%F).tar.gz \
  <project>/wiki <project>/.llm-wiki <project>/.kb-queue.json
# 向量库可选（可重建）：<project>/.index/lancedb
```

### 6.2 升级

```bash
# 1. 停服务
python -m src.cli serve-stop          # daemon 模式
# 2. 备份（见上）
# 3. 拉新代码 / 装新依赖
pip install -r requirements.lock       # 或 -e ".[dev,embedding]"
# 4. schema 迁移（如有）
python -m src.cli schema list --project <project>
python -m src.cli schema upgrade --project <project>   # 有 pending 才执行
```

### 6.3 smoke

```bash
python -m src.cli serve --host 127.0.0.1 --port 19828 --project-root <project> --daemon
curl -s http://127.0.0.1:19828/ready          # 期望 200 且无 error 项
curl -s http://127.0.0.1:19828/health          # ok:true
python -m src.cli project list                 # 项目可见
python -m src.cli health --project <project>   # H1/H2/H4
```

### 6.4 回滚

```bash
# 1. 停服务
python -m src.cli serve-stop
# 2. 恢复备份（Wiki + 元数据 + 队列）
tar -xzf backup-<date>.tar.gz
# 3. 回退代码版本（git）
git checkout <previous-tag>
# 4. 重启 + smoke（见 6.3）
```

### 6.5 向量重建

```bash
# Wiki 是事实源；向量可整体重建（R7 pending 账本会标记缺失页）
python -m src.cli vector status --project <project>     # 查看 pending
python -m src.cli vector reconcile --project <project>  # 重试 pending（需 embedding provider）
# 全量重建（可选，旧路径）：
#   ruflo migrate vector-paths --project <project> 或 rebuild-index（见 util 组）
```

## 7. 常见故障与处置

| 症状 | 诊断 | 处置 |
|---|---|---|
| `/ready` 503 | 看 `checks` 哪项 error | queue: 检查 `.kb-queue.json`；wiki: 磁盘权限；vector: embedding |
| 语义搜索无结果 | `vector status` 有 pending | `vector reconcile` 或装 `.[embedding]` |
| 任务全部死信 | `metrics` dead_letter 增长 | Provider Key/网络；`llm-providers test` |
| 端口被占用 | `serve-status` | 确认无第二实例后 `serve-stop` |
| 上传 413 | 超过 `RUFLO_MAX_UPLOAD_BYTES`（默认 50MiB） | 调大上限或拆分文件 |

// ruflo-kb — ingest view (raw file workbench §1.4).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderIngest = function renderIngest(root) {
    root.innerHTML = `
      <div class="ingest-workbench">
        <div class="ingest-left">
          <div class="ingest-toolbar">
            <label class="ingest-checkall"><input type="checkbox" id="ingestSelectAll" /> 全选未摄取</label>
            <input type="text" id="ingestFilterInput" placeholder="筛选文件名..." class="ingest-filter-input" />
            <select id="ingestStatusFilter" class="ingest-filter-select">
              <option value="all">全部状态</option>
              <option value="pending">待摄取</option>
              <option value="done">已摄取</option>
            </select>
          </div>
          <div class="ingest-file-list" id="ingestFileList">
            <div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div>
          </div>
        </div>
        <div class="ingest-right">
          <div class="ingest-actions">
            <button id="ingestSelectedBtn" class="btn-primary" disabled>提取选中 (0)</button>
            <button id="ingestAllBtn" class="btn-primary">全部提取</button>
          </div>
          <div class="ingest-progress-panel" id="ingestProgressPanel">
            <div style="color:var(--text-muted);font-size:13px;">选择左侧文件开始摄取</div>
          </div>
          <div class="ingest-manual">
            <h4 style="font-size:13px;margin:0 0 6px;">手动添加路径</h4>
            <input type="text" id="srcInput" placeholder="https://... 或 C:\\path\\to\\file.md" />
            <button id="ingBtn" class="btn-primary" style="margin-top:6px;">提交摄取</button>
            <div id="ingResult" style="margin-top:6px;"></div>
          </div>
          <div class="ingest-task-history" id="ingestTaskHistory">
            <h4 style="font-size:13px;margin:12px 0 6px;">历史任务</h4>
            <div class="task-history-list" id="taskHistoryList"><div class="skeleton skeleton-line"></div></div>
          </div>
        </div>
      </div>
    `;

    loadRawFiles();
    loadTaskHistory();

    // Manual single-source ingest
    document.getElementById("ingBtn").addEventListener("click", manualSubmit);
    document.getElementById("srcInput").addEventListener("keydown", e => { if (e.key === "Enter") manualSubmit(); });

    // Ingest selected
    document.getElementById("ingestSelectedBtn").addEventListener("click", () => {
      const checked = document.querySelectorAll("#ingestFileList input[type='checkbox']:checked");
      const paths = Array.from(checked).map(cb => cb.dataset.path);
      if (paths.length) batchIngest(paths);
    });

    // Ingest all
    document.getElementById("ingestAllBtn").addEventListener("click", () => {
      const cbs = document.querySelectorAll("#ingestFileList input[type='checkbox']");
      const paths = Array.from(cbs).map(cb => cb.dataset.path);
      if (paths.length) batchIngest(paths);
    });

    // Select all toggle
    document.getElementById("ingestSelectAll").addEventListener("change", (e) => {
      const cbs = document.querySelectorAll("#ingestFileList input[type='checkbox']");
      cbs.forEach(cb => { cb.checked = e.target.checked; });
      updateSelectedCount();
    });

    // Filter inputs
    document.getElementById("ingestFilterInput").addEventListener("input", () => renderFileList());
    document.getElementById("ingestStatusFilter").addEventListener("change", () => renderFileList());

    // Ingested file row actions (delegated)
    document.getElementById("ingestFileList").addEventListener("click", (e) => {
      const btn = e.target.closest(".reingest-btn");
      if (btn) {
        const path = btn.dataset.path;
        if (!confirm(`「${path.split("/").pop()}」已编译过 wiki 页面，重新摄取将：\n\n1. 删除现有编译结果\n2. 重新执行完整流水线\n\n确认继续？`)) return;
        doReingest(path);
        return;
      }
      const delBtn = e.target.closest("[data-action='delete-source']");
      if (delBtn) {
        const path = delBtn.dataset.path;
        if (!confirm(`删除将移除此文档已编译的所有 wiki 页面和向量（原始文件保留），确定继续？\n\n${path}`)) return;
        doDeleteSource(path);
        return;
      }
      // Quality button click → modal
      const qbtn = e.target.closest(".quality-btn");
      if (qbtn) {
        const path = qbtn.dataset.path;
        showQualityModal(path);
      }
    });

    // Quality tooltip on hover (delegated)
    document.getElementById("ingestFileList").addEventListener("mouseenter", (e) => {
      // Clean up stale tooltips
      document.querySelectorAll(".quality-tooltip").forEach(el => el.remove());
    }, true);

    document.getElementById("ingestFileList").addEventListener("mouseover", async (e) => {
      const qbtn = e.target.closest(".quality-btn");
      // Remove any existing tooltip not on this button
      document.querySelectorAll(".quality-tooltip").forEach(el => {
        if (el._target !== qbtn) el.remove();
      });
      if (!qbtn || qbtn.disabled) return;
      if (qbtn._loading) return;
      // Check if tooltip already exists for this button
      if (qbtn.querySelector(".quality-tooltip") || qbtn._tooltip) return;

      qbtn._loading = true;
      const path = qbtn.dataset.path;
      try {
        const url = `/api/v1/projects/${App.state.projectId}/quality?source_path=${encodeURIComponent(path)}`;
        const res = await fetch(url);
        if (!res.ok) { qbtn._loading = false; return; }
        const data = await res.json();
        qbtn._loading = false;
        if (!data) return;
        renderTooltip(qbtn, data);
      } catch (e) {
        qbtn._loading = false;
      }
    });

    document.getElementById("ingestFileList").addEventListener("mouseout", (e) => {
      const qbtn = e.target.closest(".quality-btn");
      if (!qbtn) {
        // Moving off the button entirely — remove tooltip after a short delay
        // so the user can move into the tooltip itself
        setTimeout(() => {
          document.querySelectorAll(".quality-tooltip").forEach(el => {
            if (!el.matches(":hover")) el.remove();
          });
        }, 200);
      }
    });

    async function loadRawFiles() {
      try {
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/raw-files`);
        App.state.rawFiles = data.files || [];
        renderFileList();
      } catch (e) {
        document.getElementById("ingestFileList").innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    function renderFileList() {
      const list = document.getElementById("ingestFileList");
      const filterText = (document.getElementById("ingestFilterInput").value || "").toLowerCase();
      const statusFilter = document.getElementById("ingestStatusFilter").value;
      let filtered = App.state.rawFiles || [];
      if (filterText) filtered = filtered.filter(f => f.name.toLowerCase().includes(filterText));
      if (statusFilter === "pending") filtered = filtered.filter(f => !f.ingested);
      if (statusFilter === "done") filtered = filtered.filter(f => f.ingested);

      if (!filtered.length) {
        list.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">📁</div>
          <div class="empty-state-title">raw/sources 目录为空</div>
          <div class="empty-state-desc">将文件放入 raw/sources 目录后刷新</div>
        </div>`;
        return;
      }

      list.innerHTML = filtered.map((f, i) => {
        const dateStr = f.created_at ? new Date(f.created_at).toLocaleDateString() : "-";
        if (f.ingested) {
          return `<div class="ingest-file-row ingested">
            <span class="ingest-file-icon" style="margin-left:4px;">${iconForExt(f.ext)}</span>
            <span class="ingest-file-name">${App.escapeHtml(f.name)}</span>
            <span class="ingest-file-date">${dateStr}</span>
            <span class="ingest-file-size">${App.formatSize(f.size)}</span>
            <button class="btn-sm reingest-btn" data-path="${App.escapeHtml(f.path)}">重新摄取</button>
            <button class="btn-sm" data-action="delete-source" data-path="${App.escapeHtml(f.path)}">删除</button>
            <button class="quality-btn" data-path="${App.escapeHtml(f.path)}">质</button>
          </div>`;
        }
        return `<div class="ingest-file-row">
          <input type="checkbox" data-path="${App.escapeHtml(f.path)}" />
          <span class="ingest-file-icon">${iconForExt(f.ext)}</span>
          <span class="ingest-file-name">${App.escapeHtml(f.name)}</span>
          <span class="ingest-file-date">${dateStr}</span>
          <span class="ingest-file-size">${App.formatSize(f.size)}</span>
          <span class="ingest-file-status"></span>
        </div>`;
      }).join("");

      list.querySelectorAll("input[type='checkbox']").forEach(cb => {
        cb.addEventListener("change", () => updateSelectedCount());
      });
      updateSelectedCount();
    }

    function updateSelectedCount() {
      const checked = document.querySelectorAll("#ingestFileList input[type='checkbox']:checked");
      const btn = document.getElementById("ingestSelectedBtn");
      btn.textContent = `提取选中 (${checked.length})`;
      btn.disabled = checked.length === 0;
    }

    function iconForExt(ext) {
      const map = { ".pdf": "📄", ".docx": "📝", ".xlsx": "📊", ".xls": "📊", ".pptx": "📽️", ".txt": "📃", ".md": "📝", ".html": "🌐", ".xml": "📋", ".json": "📋" };
      return map[ext] || "📎";
    }

    async function batchIngest(paths) {
      const panel = document.getElementById("ingestProgressPanel");
      const total = paths.length;
      panel.innerHTML = `<div class="ingest-batch-progress">
        <div class="batch-summary">摄取中 (0/${total})</div>
        <div class="progress-row">
          <div class="progress-bar" style="flex:1;height:6px;border-radius:3px;background:var(--bg-hover);">
            <div class="progress-fill" style="height:6px;border-radius:3px;width:0%;background:var(--accent);transition:width 0.3s;"></div>
          </div>
        </div>
        <div class="batch-task-list" id="batchTaskList"></div>
      </div>`;
      const fill = panel.querySelector(".progress-fill");
      const summary = panel.querySelector(".batch-summary");
      const taskList = document.getElementById("batchTaskList");

      let done = 0;
      const CONCURRENCY = 5;
      const DELAY_MS = 500;

      for (let i = 0; i < paths.length; i += CONCURRENCY) {
        const batch = paths.slice(i, i + CONCURRENCY);
        await Promise.all(batch.map(async (path, bi) => {
          const globalIdx = i + bi;
          const name = path.split("/").pop() || path;
          const taskRow = document.createElement("div");
          taskRow.className = "batch-task-row";
          taskRow.innerHTML = `<span class="batch-task-name">${App.escapeHtml(name)}</span><span class="batch-task-status">queued</span>`;
          taskList.appendChild(taskRow);
          const statusEl = taskRow.querySelector(".batch-task-status");

          await App.ingestOneRaw(path,
            () => {
              statusEl.textContent = "✓";
              statusEl.style.color = "var(--success)";
              done++;
              summary.textContent = `摄取中 (${done}/${total})`;
              fill.style.width = ((done / total) * 100) + "%";
              // Update file list status
              const f = App.state.rawFiles.find(x => x.path === path);
              if (f) f.ingested = true;
              if (done === total) {
                summary.textContent = `完成 (${done}/${total})`;
                renderFileList();
              }
            },
            (err) => {
              statusEl.textContent = "✗ " + err;
              statusEl.style.color = "var(--danger)";
              taskRow.innerHTML += `<button class="btn-sm" style="margin-left:8px;" data-retry="${App.escapeHtml(path)}">重试</button>`;
              taskRow.querySelector("[data-retry]").addEventListener("click", () => {
                taskRow.querySelector("[data-retry]").remove();
                batchIngest([path]);
              });
              done++;
              summary.textContent = `摄取中 (${done}/${total})`;
              fill.style.width = ((done / total) * 100) + "%";
            },
            (rec) => {
              const stages = Array.isArray(rec.stages) ? rec.stages : [];
              const stageName = stages.length ? stages[stages.length - 1].name : rec.status;
              statusEl.textContent = stageName || rec.status;
            }
          );
        }));
        if (i + CONCURRENCY < paths.length) {
          await new Promise(r => setTimeout(r, DELAY_MS));
        }
      }
    }

    async function doReingest(path) {
      const panel = document.getElementById("ingestProgressPanel");
      panel.innerHTML = `<div class="ingest-progress">
        <div class="banner-warn">正在重新摄取（会先清理旧结果）…</div>
        <div class="progress-row">
          <div class="progress-bar"><div class="progress-fill" style="width:20%"></div></div>
          <span class="progress-status">cleaning</span>
        </div>
      </div>`;

      try {
        const r = await App.api(`/api/v1/projects/${App.state.projectId}/reingest`, {
          method: "POST",
          body: { source_path: path },
        });
        if (r.status !== "queued" || !r.taskId) {
          panel.innerHTML = `<div class="banner-warn">未识别状态: ${App.escapeHtml(JSON.stringify(r))}</div>`;
          return;
        }
        // Poll the reingest task status (reuse ingestOneRaw's polling by
        // wrapping the task id through a manual loop).
        const poll = await pollTask(r.taskId);
        if (poll) renderFileList();
      } catch (e) {
        panel.innerHTML = `<div class="banner-err">重新摄取失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    async function pollTask(taskId) {
      const panel = document.getElementById("ingestProgressPanel");
      const statusEl = panel.querySelector(".progress-status");
      const fill = panel.querySelector(".progress-fill");
      for (let i = 0; i < 240; i++) {
        await new Promise(res => setTimeout(res, 1500));
        let rec;
        try {
          rec = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/status/${encodeURIComponent(taskId)}`);
        } catch (e) {
          statusEl.textContent = "查询失败: " + e.message;
          return false;
        }
        statusEl.textContent = rec.status;
        const stages = Array.isArray(rec.stages) ? rec.stages : [];
        const pct = ({ queued: 5, running: 30, finished: 100, succeeded: 100, failed: 100, ignored: 100 }[rec.status])
          ?? (stages.length >= 3 ? 95 : stages.length === 2 ? 70 : stages.length === 1 ? 40 : 30);
        fill.style.width = pct + "%";
        if (rec.status === "succeeded") {
          panel.innerHTML = `<div class="banner-ok">✓ 重新摄取完成</div>`;
          return true;
        }
        if (rec.status === "failed") {
          panel.innerHTML = `<div class="banner-err">✗ 重新摄取失败${rec.error ? ": " + App.escapeHtml(rec.error) : ""}</div>`;
          return false;
        }
      }
      panel.innerHTML = `<div class="banner-warn">重新摄取超时，请到任务历史查看。</div>`;
      return false;
    }

    async function doDeleteSource(path) {
      const panel = document.getElementById("ingestProgressPanel");
      panel.innerHTML = `<div class="ingest-progress">
        <div class="banner-warn">正在删除已编译的 wiki 信息…</div>
        <div class="progress-row">
          <div class="progress-bar"><div class="progress-fill" style="width:50%"></div></div>
          <span class="progress-status">deleting</span>
        </div>
      </div>`;

      try {
        const r = await App.api(`/api/v1/projects/${App.state.projectId}/delete-source`, {
          method: "POST",
          body: { source_path: path },
        });
        const nDel = (r.deleted_pages || []).length;
        const nUpd = (r.updated_pages || []).length;
        const nVec = r.deleted_vectors ?? 0;
        panel.innerHTML = `<div class="banner-ok">✓ 已删除（删除 ${nDel} 页，更新 ${nUpd} 页，清理 ${nVec} 条向量）</div>`;
        renderFileList();
      } catch (e) {
        panel.innerHTML = `<div class="banner-err">删除失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    async function loadTaskHistory() {
      const listEl = document.getElementById("taskHistoryList");
      if (!listEl) return;
      try {
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/tasks`);
        const tasks = data.tasks || [];
        if (!tasks.length) {
          listEl.innerHTML = `<div class="task-history-empty">暂无任务</div>`;
          return;
        }
        listEl.innerHTML = tasks.slice(0, 20).map(t => {
          const name = (t.source_path || t.source || "").split("/").pop() || t.task_id || "";
          const icon = ({ succeeded: "✓", failed: "✗", running: "⏳", queued: "⏳", ignored: "⏭" }[t.status]) || "•";
          const cls = ({ succeeded: "ok", failed: "err", running: "run", queued: "run", ignored: "ign" }[t.status]) || "";
          const started = t.started_at ? new Date(t.started_at).toLocaleTimeString() : "";
          let duration = "";
          if (t.finished_at && t.started_at) {
            const s = (t.finished_at - t.started_at) / 1000;
            duration = (s >= 60 ? (s / 60).toFixed(1) + "m" : s.toFixed(1) + "s");
          }
          const err = t.error ? " · " + App.escapeHtml(String(t.error).slice(0, 40)) : "";
          return `<div class="task-history-row ${cls}" title="${App.escapeHtml(t.task_id || "")}">
            <span class="task-history-icon">${icon}</span>
            <span class="task-history-name">${App.escapeHtml(name)}</span>
            <span class="task-history-time">${App.escapeHtml(started)}</span>
            <span class="task-history-dur">${App.escapeHtml(duration)}</span>
            <span class="task-history-err">${err}</span>
          </div>`;
        }).join("");
      } catch (e) {
        listEl.innerHTML = `<div class="task-history-empty">加载失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    async function manualSubmit() {
      const src = document.getElementById("srcInput").value.trim();
      const out = document.getElementById("ingResult");
      if (!src) { out.innerHTML = `<div class="banner-warn">请输入 URL 或文件路径。</div>`; return; }
      const btn = document.getElementById("ingBtn");
      btn.disabled = true; btn.textContent = "提交中...";
      out.innerHTML = "";
      try {
        const r = await App.api(`/api/v1/projects/${App.state.projectId}/ingest`, {
          method: "POST",
          body: { source: src, folderContext: null },
        });
        if (r.status === "ignored") {
          out.innerHTML = `<div class="banner-warn">已存在，已跳过（reason=${App.escapeHtml(r.reason || "Duplicate")}）。</div>`;
          return;
        }
        if (r.status !== "queued" || !r.taskId) {
          out.innerHTML = `<div class="banner-warn">未识别状态: ${App.escapeHtml(JSON.stringify(r))}</div>`;
          return;
        }
        const panel = document.createElement("div");
        panel.className = "ingest-progress";
        panel.innerHTML = `
          <div class="banner-ok">已入队 (taskId=${App.escapeHtml(r.taskId)})</div>
          <div class="progress-row">
            <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
            <span class="progress-status">queued</span>
          </div>
          <div class="progress-stages"></div>
        `;
        out.appendChild(panel);
        const fill = panel.querySelector(".progress-fill");
        const statusEl = panel.querySelector(".progress-status");
        const stagesEl = panel.querySelector(".progress-stages");

        for (let i = 0; i < 240; i++) {
          await new Promise(r => setTimeout(r, 1500));
          let rec;
          try {
            rec = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/status/${encodeURIComponent(r.taskId)}`);
          } catch (e) {
            statusEl.textContent = "查询失败: " + e.message;
            break;
          }
          statusEl.textContent = rec.status;
          const stages = Array.isArray(rec.stages) ? rec.stages : [];
          stagesEl.innerHTML = stages.length
            ? stages.map(s => `<span class="stage-badge">${App.escapeHtml(s.name)}</span>`).join(" · ")
            : "<span style='color:#9ca3af'>等待阶段事件...</span>";
          const pct = ({
            queued: 5, running: 30, finished: 100,
            succeeded: 100, failed: 100, ignored: 100,
          }[rec.status]) ?? (stages.length >= 3 ? 95 : stages.length === 2 ? 70 : stages.length === 1 ? 40 : 30);
          fill.style.width = pct + "%";
          if (rec.status === "succeeded" || rec.status === "failed") {
            if (rec.status === "succeeded") {
              panel.querySelector(".banner-ok").outerHTML = `<div class="banner-ok">✓ 摄取完成</div>`;
            } else {
              panel.querySelector(".banner-ok").outerHTML = `<div class="banner-err">✗ 摄取失败${rec.error ? ": " + App.escapeHtml(rec.error) : ""}</div>`;
            }
            break;
          }
        }
      } catch (e) {
        out.innerHTML = `<div class="banner-err">摄取失败: ${App.escapeHtml(e.message)}</div>`;
      } finally {
        btn.disabled = false; btn.textContent = "提交摄取";
      }
    }

    // ── Quality helpers ──────────────────────────────────────────────

    function renderTooltipContent(data) {
      const passed = data.passed;
      const exists = data.exists;
      const report = data.report || {};
      const verdict = report.verdict || "—";
      const warnings = (report.warnings || []).length;
      const pages = report.pages_total ?? "—";
      const confidence = report.candidate_confidence != null
        ? (report.candidate_confidence * 100).toFixed(0) + "%"
        : "—";
      const reviewCount = (data.review_items || []).length;
      const quarantineCount = (data.quarantine || []).length;
      const verdictReason = report.verdict_reason || "";

      let color = exists ? (passed ? "var(--success)" : "var(--danger)") : "var(--text-muted)";
      let statusText = exists ? (passed ? "✓ 质检通过" : "✗ 质检未通过") : "无质检报告";

      let lines = [
        `<span style="color:${color};font-weight:600;">${statusText}</span>`,
        `判决: ${App.escapeHtml(verdict)}`,
        `页数: ${pages}`,
        `置信度: ${confidence}`,
      ];
      if (warnings) lines.push(`警告: ${warnings} 条`);
      if (reviewCount) lines.push(`审查项: ${reviewCount} 条`);
      if (quarantineCount) lines.push(`隔离页: ${quarantineCount} 条`);
      if (verdictReason) lines.push(`原因: ${App.escapeHtml(verdictReason)}`);

      return lines.join("<br>");
    }

    function renderTooltip(btn, data) {
      // Remove any existing tooltip
      document.querySelectorAll(".quality-tooltip").forEach(el => el.remove());
      const tip = document.createElement("div");
      tip.className = "quality-tooltip";
      tip._target = btn;
      tip.innerHTML = renderTooltipContent(data);
      // Position below the button
      const rect = btn.getBoundingClientRect();
      tip.style.left = Math.max(4, rect.left + rect.width / 2 - 120) + "px";
      tip.style.top = (rect.bottom + 4) + "px";
      document.body.appendChild(tip);
      btn._tooltip = tip;
      // Remove tooltip on mouse leave of the tooltip itself
      tip.addEventListener("mouseleave", () => {
        tip.remove();
        btn._tooltip = null;
      });
    }

    function showQualityModal(path) {
      // Remove existing modal
      document.querySelectorAll(".quality-modal-overlay").forEach(el => el.remove());

      const overlay = document.createElement("div");
      overlay.className = "quality-modal-overlay";
      overlay.innerHTML = `
        <div class="quality-modal-card">
          <div class="quality-modal-header">
            <h3>质检报告</h3>
            <button class="quality-modal-close">&times;</button>
          </div>
          <div class="quality-modal-body">
            <div class="quality-modal-loading">加载中...</div>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const close = () => overlay.remove();
      overlay.querySelector(".quality-modal-close").addEventListener("click", close);
      overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

      // Fetch data
      const bodyEl = overlay.querySelector(".quality-modal-body");
      (async () => {
        try {
          const url = `/api/v1/projects/${App.state.projectId}/quality?source_path=${encodeURIComponent(path)}`;
          const res = await fetch(url);
          if (!res.ok) {
            bodyEl.innerHTML = `<div class="banner-err">加载失败: ${res.status}</div>`;
            return;
          }
          const data = await res.json();
          renderQualityModalBody(bodyEl, data);
        } catch (e) {
          bodyEl.innerHTML = `<div class="banner-err">请求失败: ${App.escapeHtml(e.message)}</div>`;
        }
      })();
    }

    function renderQualityModalBody(el, data) {
      const passed = data.passed;
      const exists = data.exists;
      const report = data.report || {};
      const reviewItems = data.review_items || [];
      const quarantine = data.quarantine || [];

      const verdict = report.verdict || "—";
      const verdictReason = report.verdict_reason || "";
      const pagesTotal = report.pages_total ?? "—";
      const pagesByType = report.pages_by_type || {};
      const confidence = report.candidate_confidence != null
        ? (report.candidate_confidence * 100).toFixed(0) + "%"
        : "—";
      const warnings = report.warnings || [];
      const sourceBytes = report.source_bytes ?? "—";
      const chunksCount = report.chunks_count ?? "—";
      const claimsCount = report.claims_count ?? "—";
      const evidenceCount = report.evidence_count ?? "—";
      const durationMs = report.duration_ms ?? null;
      const finishedAt = report.finished_at ? new Date(report.finished_at).toLocaleString() : "—";

      let passColor = exists ? (passed ? "var(--success)" : "var(--danger)") : "var(--text-muted)";
      let passText = exists ? (passed ? "✓ 通过" : "✗ 未通过") : "无报告";

      let html = `
        <div class="qm-summary">
          <span class="qm-badge" style="color:${passColor};font-weight:700;font-size:18px;">${passText}</span>
          <span class="qm-verdict">判决: ${App.escapeHtml(verdict)}</span>
        </div>
      `;

      if (verdictReason) {
        html += `<div class="qm-section"><div class="qm-section-title">判决原因</div><div class="qm-value">${App.escapeHtml(verdictReason)}</div></div>`;
      }

      html += `<div class="qm-section">
        <div class="qm-section-title">基本信息</div>
        <table class="qm-table">
          <tr><td>源文件大小</td><td>${App.formatSize(sourceBytes)}</td></tr>
          <tr><td>分块数</td><td>${chunksCount}</td></tr>
          <tr><td>声明数</td><td>${claimsCount}</td></tr>
          <tr><td>证据数</td><td>${evidenceCount}</td></tr>
          <tr><td>置信度</td><td>${confidence}</td></tr>
          <tr><td>总页数</td><td>${pagesTotal}</td></tr>
      `;
      for (const [type, count] of Object.entries(pagesByType)) {
        html += `<tr><td>— ${App.escapeHtml(type)}</td><td>${count}</td></tr>`;
      }
      if (durationMs) {
        html += `<tr><td>耗时</td><td>${(durationMs / 1000).toFixed(1)}s</td></tr>`;
      }
      html += `<tr><td>完成时间</td><td>${App.escapeHtml(finishedAt)}</td></tr>`;
      html += `</table></div>`;

      // Warnings
      if (warnings.length) {
        html += `<div class="qm-section">
          <div class="qm-section-title">警告 (${warnings.length})</div>
          <ul class="qm-list">${warnings.map(w => `<li class="qm-warn">${App.escapeHtml(w)}</li>`).join("")}</ul>
        </div>`;
      }

      // Review items
      if (reviewItems.length) {
        html += `<div class="qm-section">
          <div class="qm-section-title">审查项 (${reviewItems.length})</div>
          <ul class="qm-list">${reviewItems.map(ri => `
            <li class="qm-review-item">
              <strong>${App.escapeHtml(ri.title || "")}</strong>
              <span class="qm-tag qm-tag-${ri.status || "open"}">${App.escapeHtml(ri.status || "open")}</span>
              ${ri.detail ? `<br><span class="qm-detail">${App.escapeHtml(ri.detail)}</span>` : ""}
            </li>
          `).join("")}</ul>
        </div>`;
      }

      // Quarantine
      if (quarantine.length) {
        html += `<div class="qm-section">
          <div class="qm-section-title">隔离页 (${quarantine.length})</div>
          <ul class="qm-list">${quarantine.map(q => `
            <li class="qm-quarantine-item">
              <strong>${App.escapeHtml(q.page_id || "")}</strong>
              <span class="qm-tag qm-tag-${q.verdict === "pass" ? "pass" : "reject"}">${App.escapeHtml(q.verdict || "")}</span>
              <span class="qm-score">分数: ${q.total_score != null ? q.total_score.toFixed(2) : "—"}</span>
              ${(q.issues || []).length ? `<br><span class="qm-detail">问题: ${App.escapeHtml(q.issues.join("; "))}</span>` : ""}
            </li>
          `).join("")}</ul>
        </div>`;
      }

      if (!exists) {
        html += `<div class="qm-section" style="color:var(--text-muted);">该文件尚未摄取或尚无质检报告。</div>`;
      }

      el.innerHTML = html;
    }
  };
})();

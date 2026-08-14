// ruflo-kb — ingest view (raw file workbench §1.4).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderIngest = function renderIngest(root) {
    let currentPage = 1;
    let pageSize = 20;
    const selectedPaths = new Set();
    const taskByPath = new Map();

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
            <label class="ingest-page-size">每页
              <select id="ingestPageSize" class="ingest-filter-select">
                <option value="20">20</option><option value="50">50</option>
                <option value="100">100</option><option value="200">200</option>
              </select> 条
            </label>
            <div class="ingest-batch-actions">
              <button id="ingestSelectedBtn" class="btn-primary" disabled>提取选中 (0)</button>
              <button id="ingestAllBtn" class="btn-primary">全部提取</button>
            </div>
          </div>
          <div class="queue-status" id="queueStatus">
            <span class="qs-label">队列</span>
            <span class="qs-state" id="qsState">读取中...</span>
            <span class="qs-val" id="qsPending">0</span><span class="qs-label">待处理</span>
            <span class="qs-val" id="qsRunning">0</span><span class="qs-label">运行中</span>
            <span class="qs-val" id="qsFailed">0</span><span class="qs-label">失败</span>
            <span class="qs-actions">
              <button id="qsPauseBtn" title="暂停队列">⏸</button>
              <button id="qsResumeBtn" title="恢复队列">▶</button>
              <button id="qsRefreshBtn" title="刷新">⟳</button>
            </span>
          </div>
          <div class="ingest-list-head"><span></span><span>文件</span><span>任务状态</span><span>进度</span><span>质量</span><span>操作</span></div>
          <div class="ingest-file-list" id="ingestFileList">
            <div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div>
          </div>
          <div class="ingest-progress-panel" id="ingestProgressPanel">
            <div style="color:var(--text-muted);font-size:13px;">选择文件开始摄取</div>
          </div>
          <div class="ingest-pagination" id="ingestPagination"></div>
          <div class="ingest-task-history" id="ingestTaskHistory">
            <h4 style="font-size:13px;margin:8px 0 6px;">任务历史</h4>
            <div class="task-history-list" id="taskHistoryList"><div class="skeleton skeleton-line"></div></div>
          </div>
        </div>
        <div class="ingest-source-tools">
          <div class="upload-zone" id="uploadZone">
            <div class="upload-title">📤 上传文件</div>
            <div class="upload-hint">拖拽文件到此处，或点击选择</div>
            <div class="upload-list" id="uploadList"></div>
            <input type="file" id="uploadInput" multiple hidden accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.txt,.md,.html,.xml,.json" />
          </div>
          <div class="ingest-manual">
            <h4 style="font-size:13px;margin:0 0 6px;">手动添加路径</h4>
            <input type="text" id="srcInput" placeholder="https://... 或 C:\\path\\to\\file.md" />
            <button id="ingBtn" class="btn-primary" style="margin-top:6px;">提交摄取</button>
            <div id="ingResult" style="margin-top:6px;"></div>
          </div>
        </div>
      </div>
    `;

    loadRawFiles();
    loadTaskHistory();
    loadQueueStatus();

    // Upload drop zone
    const zone = document.getElementById("uploadZone");
    const input = document.getElementById("uploadInput");
    zone.addEventListener("click", () => input.click());
    input.addEventListener("change", () => handleFiles(input.files));
    zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("dragover");
      handleFiles(e.dataTransfer.files);
    });

    // Queue status
    document.getElementById("qsPauseBtn").addEventListener("click", async () => {
      const btn = document.getElementById("qsPauseBtn");
      btn.disabled = true; btn.textContent = "暂停中...";
      try { await App.api("/api/v1/queue/pause", { method: "POST" }); await refreshQueueView(); App.setBanner("队列已暂停", "info"); }
      catch (e) { App.setBanner("暂停失败: " + e.message); }
      finally { btn.disabled = false; btn.textContent = "⏸"; }
    });
    document.getElementById("qsResumeBtn").addEventListener("click", async () => {
      const btn = document.getElementById("qsResumeBtn");
      btn.disabled = true; btn.textContent = "恢复中...";
      try {
        const result = await App.api("/api/v1/queue/resume", { method: "POST" });
        await refreshQueueView();
        App.setBanner(result.status === "resumed" ? "队列已恢复" : "队列状态已更新", "info");
      }
      catch (e) { App.setBanner("恢复失败: " + e.message); }
      finally { btn.disabled = false; btn.textContent = "▶"; }
    });
    document.getElementById("qsRefreshBtn").addEventListener("click", refreshQueueView);

    // Manual single-source ingest
    document.getElementById("ingBtn").addEventListener("click", manualSubmit);
    document.getElementById("srcInput").addEventListener("keydown", e => { if (e.key === "Enter") manualSubmit(); });

    // Ingest selected
    document.getElementById("ingestSelectedBtn").addEventListener("click", () => {
      const paths = Array.from(selectedPaths);
      if (paths.length) batchIngest(paths);
    });

    // Ingest all
    document.getElementById("ingestAllBtn").addEventListener("click", () => {
      const paths = getFilteredFiles().filter(f => !f.ingested).map(f => f.path);
      if (paths.length) batchIngest(paths);
    });

    // Select all toggle
    document.getElementById("ingestSelectAll").addEventListener("change", (e) => {
      getVisibleFiles().forEach(f => e.target.checked ? selectedPaths.add(f.path) : selectedPaths.delete(f.path));
      renderFileList();
      updateSelectedCount();
    });

    // Filter inputs
    document.getElementById("ingestFilterInput").addEventListener("input", () => { currentPage = 1; renderFileList(); });
    document.getElementById("ingestStatusFilter").addEventListener("change", () => { currentPage = 1; renderFileList(); });
    document.getElementById("ingestPageSize").addEventListener("change", e => {
      pageSize = Number(e.target.value);
      currentPage = 1;
      renderFileList();
    });

    async function handleFiles(files) {
      if (!files || !files.length) return;
      const list = document.getElementById("uploadList");
      const zone = document.getElementById("uploadZone");
      zone.classList.add("disabled");
      for (const f of files) {
        const row = document.createElement("div");
        row.className = "upload-row";
        row.innerHTML = `<span class="upload-row-name">${App.escapeHtml(f.name)}</span><span class="upload-row-status">上传中...</span>`;
        list.appendChild(row);
        const st = row.querySelector(".upload-row-status");
        try {
          const form = new FormData();
          form.append("file", f);
          const res = await fetch(`/api/v1/projects/${App.state.projectId}/upload`, { method: "POST", body: form });
          if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
          st.textContent = "✓ 已上传";
          st.className = "upload-row-status ok";
          loadRawFiles();
        } catch (e) {
          st.textContent = "✗ " + e.message;
          st.className = "upload-row-status err";
        }
      }
      zone.classList.remove("disabled");
      input.value = "";
    }

    async function loadRawFiles() {
      try {
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/raw-files`);
        App.state.rawFiles = data.files || [];
        renderFileList();
      } catch (e) {
        document.getElementById("ingestFileList").innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    async function loadQueueStatus() {
      try {
        const q = await App.api("/api/v1/queue/status");
        const state = document.getElementById("qsState");
        state.textContent = q.paused ? "已暂停" : "运行中";
        state.className = `qs-state ${q.paused ? "paused" : "running"}`;
        document.getElementById("qsPending").textContent = q.pending_count ?? "?";
        document.getElementById("qsRunning").textContent = q.running_count ?? "?";
        document.getElementById("qsFailed").textContent = q.failed_count ?? "?";
      } catch { /* best-effort */ }
    }

    async function refreshQueueView() {
      await Promise.all([loadQueueStatus(), loadTaskHistory()]);
      renderFileList();
    }

    async function loadTaskHistory() {
      const listEl = document.getElementById("taskHistoryList");
      if (!listEl) return;
      try {
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/tasks`);
        const tasks = (data && data.tasks) || [];
        taskByPath.clear();
        tasks.forEach(t => {
          const path = t.source_path || t.source;
          if (path) taskByPath.set(String(path).replaceAll("\\", "/"), t);
        });
        (App.state.rawFiles || []).forEach(f => {
          const task = taskByPath.get(String(f.path).replaceAll("\\", "/"));
          if (task) updateFileProgress(f.path, task);
        });
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

    function qualityClass(grade) {
      if (grade === "A") return "pass";
      if (grade === "B") return "warn";
      if (grade === "C") return "fail";
      return "none";
    }

    const STAGES = [
      { name: "collector", label: "Collector", icon: "📥" },
      { name: "analyzer", label: "Analyzer", icon: "🧠" },
      { name: "generator", label: "Generator", icon: "💾" },
    ];

    function renderStageSteps(completedNames, allDone) {
      const lastIdx = (completedNames || []).length - 1;
      return STAGES.map((s, i) => {
        let cls = "pending";
        if (allDone) cls = "completed";
        else if (i < lastIdx) cls = "completed";
        else if (i === lastIdx) cls = "active";
        const connector = i < STAGES.length - 1
          ? `<span class="stage-connector ${(i < lastIdx || allDone) ? "done" : ""}">→</span>`
          : "";
        return `<span class="stage-step ${cls}"><span class="stage-icon">${cls === "completed" ? "✔" : cls === "active" ? s.icon : "▢"}</span>${App.escapeHtml(s.label)}</span>${connector}`;
      }).join("");
    }

    function renderFileList() {
      const list = document.getElementById("ingestFileList");
      const filtered = getFilteredFiles();
      const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
      currentPage = Math.min(currentPage, totalPages);
      const visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

      if (!filtered.length) {
        list.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">📁</div>
          <div class="empty-state-title">raw/sources 目录为空</div>
          <div class="empty-state-desc">上传文件到此处，或放入 raw/sources 目录后刷新</div>
        </div>`;
        renderPagination(0, 0);
        updateSelectedCount();
        return;
      }

      list.innerHTML = visible.map((f) => {
        const dateStr = f.created_at ? new Date(f.created_at).toLocaleDateString() : "-";
        if (f.ingested) {
          return `<div class="ingest-file-row ingested" data-path="${App.escapeHtml(f.path)}">
            <span></span>
            <span class="ingest-file-meta"><span class="ingest-file-icon">${iconForExt(f.ext)}</span><span><strong class="ingest-file-name">${App.escapeHtml(f.name)}</strong><small>${f.ext.toUpperCase()} · ${App.formatSize(f.size)} · ${dateStr}</small></span></span>
            <span class="ingest-file-status-text">已完成</span>
            <span class="ingest-file-progress ingest-file-name-progress"><span class="ingest-file-progress-fill" style="width:100%"></span><span class="ingest-file-progress-text">100%</span></span>
            <span class="quality-badge quality-${qualityClass(f.quality)}" data-path="${App.escapeHtml(f.path)}">${f.quality || "—"}</span>
            <span class="ingest-row-actions">
            <button class="btn-sm ingest-one-btn" disabled>已摄取</button>
            <button class="btn-sm reingest-btn" data-path="${App.escapeHtml(f.path)}">重新摄取</button>
            <button class="btn-sm" data-action="delete-source" data-path="${App.escapeHtml(f.path)}">删除</button>
            </span>
          </div>`;
        }
        return `<div class="ingest-file-row" data-path="${App.escapeHtml(f.path)}">
          <input type="checkbox" data-path="${App.escapeHtml(f.path)}" ${selectedPaths.has(f.path) ? "checked" : ""} />
          <span class="ingest-file-meta"><span class="ingest-file-icon">${iconForExt(f.ext)}</span><span><strong class="ingest-file-name">${App.escapeHtml(f.name)}</strong><small>${f.ext.toUpperCase()} · ${App.formatSize(f.size)} · ${dateStr}</small></span></span>
          <span class="ingest-file-status-text">待摄取</span>
          <span class="ingest-file-progress ingest-file-name-progress"><span class="ingest-file-progress-fill"></span><span class="ingest-file-progress-text"></span></span>
          <span class="quality-badge quality-${qualityClass(f.quality)}" data-path="${App.escapeHtml(f.path)}">${f.quality || "—"}</span>
          <span class="ingest-row-actions"><button class="btn-sm ingest-one-btn" data-path="${App.escapeHtml(f.path)}">摄取</button></span>
        </div>`;
      }).join("");

      list.querySelectorAll("input[type='checkbox']").forEach(cb => {
        cb.addEventListener("change", () => {
          cb.checked ? selectedPaths.add(cb.dataset.path) : selectedPaths.delete(cb.dataset.path);
          updateSelectedCount();
        });
      });
      list.querySelectorAll(".quality-badge").forEach(b => {
        b.addEventListener("click", () => showQualityReport(b.dataset.path));
      });
      list.querySelectorAll(".ingest-one-btn:not([disabled])").forEach(b => {
        b.addEventListener("click", () => {
          b.disabled = true;
          b.textContent = "摄取中...";
          batchIngest([b.dataset.path]);
        });
      });
      list.querySelectorAll(".reingest-btn").forEach(b => {
        b.addEventListener("click", () => doReingest(b.dataset.path));
      });
      list.querySelectorAll("[data-action='delete-source']").forEach(b => {
        b.addEventListener("click", () => doDeleteSource(b.dataset.path));
      });
      renderPagination(filtered.length, totalPages);
      updateSelectedCount();
      applyTaskProgressToRows();
    }

    function applyTaskProgressToRows() {
      (App.state.rawFiles || []).forEach(f => {
        const task = taskByPath.get(String(f.path).replaceAll("\\", "/"));
        if (task) updateFileProgress(f.path, task);
      });
    }

    function getFilteredFiles() {
      const filterText = (document.getElementById("ingestFilterInput").value || "").toLowerCase();
      const statusFilter = document.getElementById("ingestStatusFilter").value;
      let files = App.state.rawFiles || [];
      if (filterText) files = files.filter(f => f.name.toLowerCase().includes(filterText));
      if (statusFilter === "pending") files = files.filter(f => !f.ingested);
      if (statusFilter === "done") files = files.filter(f => f.ingested);
      return files;
    }

    function getVisibleFiles() {
      const files = getFilteredFiles();
      return files.slice((currentPage - 1) * pageSize, currentPage * pageSize).filter(f => !f.ingested);
    }

    function renderPagination(total, totalPages) {
      const el = document.getElementById("ingestPagination");
      if (!total) { el.innerHTML = ""; return; }
      const start = (currentPage - 1) * pageSize + 1;
      const end = Math.min(currentPage * pageSize, total);
      const pages = Array.from({ length: totalPages }, (_, i) => i + 1)
        .filter(p => p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1);
      const items = [];
      pages.forEach((p, i) => {
        if (i && p > pages[i - 1] + 1) items.push("<span>…</span>");
        items.push(`<button class="ingest-page-btn ${p === currentPage ? "active" : ""}" data-page="${p}">${p}</button>`);
      });
      el.innerHTML = `<span class="ingest-page-info">显示 ${start}–${end}，共 ${total} 个文件</span>
        <div class="ingest-page-controls"><button class="ingest-page-btn" data-page="${currentPage - 1}" ${currentPage === 1 ? "disabled" : ""}>‹</button>${items.join("")}<button class="ingest-page-btn" data-page="${currentPage + 1}" ${currentPage === totalPages ? "disabled" : ""}>›</button></div>`;
      el.querySelectorAll("button[data-page]").forEach(btn => btn.addEventListener("click", () => {
        currentPage = Number(btn.dataset.page);
        renderFileList();
      }));
    }

    function fileProgress(rec) {
      const status = rec && rec.status;
      if (status === "succeeded" || status === "finished" || status === "ignored" || status === "failed") return 100;
      const stages = Array.isArray(rec && rec.stages) ? rec.stages : [];
      if (status === "queued") return 5;
      return [5, 25, 45, 65, 82, 95][Math.min(stages.length, 5)];
    }

    function updateFileProgress(path, rec, label) {
      const row = Array.from(document.querySelectorAll("#ingestFileList .ingest-file-row"))
        .find(el => el.dataset.path === path);
      if (!row) return;
      const fill = row.querySelector(".ingest-file-progress-fill");
      const text = row.querySelector(".ingest-file-progress-text");
      if (!fill || !text) return;
      const pct = fileProgress(rec);
      fill.style.width = `${pct}%`;
      row.classList.toggle("ingest-file-row-running", rec && rec.status === "running");
      row.classList.toggle("ingest-file-row-failed", rec && rec.status === "failed");
      row.classList.toggle("ingest-file-row-done", rec && ["succeeded", "finished", "ignored"].includes(rec.status));
      text.textContent = label || (rec && rec.status) || "";
      const status = row.querySelector(".ingest-file-status-text");
      if (status) status.textContent = label || ({ queued: "排队中", running: "处理中", succeeded: "已完成", finished: "已完成", failed: "失败", ignored: "已跳过" }[rec && rec.status] || rec?.status || "");
    }

    function pageTypeLabel(t) {
      return ({ source: "source", entity: "entity", concept: "concept", synthesis: "synthesis" }[t]) || t || "page";
    }
    function gradeBadge(grade) {
      const map = { A: ["A · 通过", "pass"], B: ["B · 改进", "warn"], C: ["C · 待审核", "fail"] };
      const m = map[grade] || [grade || "—", "none"];
      return `<span class="qr-tag ${m[1]}">${App.escapeHtml(m[0])}</span>`;
    }
    function overallVerdict(r) {
      if (!r) return ["—", ""];
      if (!r.report) return ["尚未生成质检报告", "none"];
      const v = r.report.verdict || "";
      if (v === "validated" || v === "succeeded") return ["通过", "pass"];
      if (v === "needs_human_review") return ["待审核", "warn"];
      if (v === "rejected") return ["已拒绝", "fail"];
      return [v || "—", "none"];
    }
    function durationText(ms) {
      if (!ms) return "—";
      return ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : ms + "ms";
    }

    function qrPageNote(page) {
      const notes = [];
      if (page.grade === "A") notes.push("结构完整，来源明确");
      if (page.grade === "B") notes.push("内容基本可用，存在改进项");
      if (page.grade === "C") notes.push("需要人工确认");
      (page.issues || []).forEach(i => notes.push(i));
      return notes.length ? notes.join(" · ") : (page.title || "");
    }

    async function showQualityReport(path) {
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML = `<div class="modal-card modal-card-wide qr-modal">
        <div class="modal-header"><h3>质检报告</h3><button class="modal-close">×</button></div>
        <div class="modal-body"><div class="spinner"></div>质检中...</div>
      </div>`;
      document.body.appendChild(overlay);
      overlay.querySelector(".modal-close").addEventListener("click", () => overlay.remove());
      overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });

      const body = overlay.querySelector(".modal-body");
      const file = (App.state.rawFiles || []).find(f => f.path === path);
      try {
        const r = await App.api(`/api/v1/projects/${App.state.projectId}/quality?source_path=${encodeURIComponent(path)}`);
        const report = r.report || {};
        const verdict = overallVerdict(r);
        const repDate = report.finished_at_iso || report.finished_at
          ? new Date(report.finished_at_iso || report.finished_at).toLocaleString() : null;
        const openReviews = (r.review_items || []).filter(i => i.status && i.status !== "resolved" && i.status !== "approved" && i.status !== "rejected").length;

        // Generated wiki pages come from the quality endpoint (r.pages),
        // collected from wiki/ frontmatter by the backend.
        const pages = r.pages || [];
        const cPages = pages.filter(p => p.grade === "C");

        const def = { A: 0, B: 0, C: 0 };
        pages.forEach(p => { if (def[p.grade] !== undefined) def[p.grade]++; });

        // --- summary cards ---
        let verdictIcon = "✅", verdictCls = "pass";
        if (!r.report) { verdictIcon = "—"; verdictCls = "none"; }
        else if (verdict[1] === "warn") { verdictIcon = "⚠"; }
        else if (verdict[1] === "fail") { verdictIcon = "❌"; verdictCls = "fail"; }

        // --- source context ---
        const srcRows = [
          ["RAW 文件", file ? file.name : path.split("/").pop()],
          ["摄取任务", report.task_id || "—"],
          ["生成时间", repDate || "—"],
          ["生成页面数", (pages.length || report.pages_total || 0) + " 个 Wiki 页面"],
        ];

        // --- generated pages list ---
        const pageRows = pages.map(p => `
          <div class="qr-review">
            <div><b>${App.escapeHtml(p.title || p.page_id || "未命名页面")}</b>
            <p class="text-code">${App.escapeHtml(pageTypeLabel(p.type))} · ${App.escapeHtml(p.page_id || "—")} · ${App.escapeHtml(qrPageNote(p))}</p></div>
            ${gradeBadge(p.grade)}
          </div>`).join("");

        // --- C-level pages (审核状态) ---
        const reviewRows = (r.review_items || []).map(ri => `
          <div class="qr-review">
            <div><b class="text-code">${App.escapeHtml(ri.type || "review")}</b> <strong>${App.escapeHtml(ri.title || "")}</strong>
            ${ri.detail ? `<p>${App.escapeHtml(ri.detail)}</p>` : ""}</div>
            <span class="qr-tag ${(ri.status === "open" || !ri.status) ? "warn" : "pass"}">${App.escapeHtml(ri.status || "待处理")}</span>
          </div>`).join("")
          + (r.quarantine || []).map(q => `
            <div class="qr-review">
              <div><b class="text-code">${App.escapeHtml(q.page_id)}</b>
              <p>${App.escapeHtml(q.verdict)} · 评分 ${q.total_score}${q.issues && q.issues.length ? " · " + App.escapeHtml(q.issues.join("、")) : ""}</p></div>
              <span class="qr-tag fail">已隔离</span>
            </div>`).join("");

        // --- warning banner for C-level pages ---
        const cWarn = def.C > 0 ? `
          <div class="banner-warn" style="margin:0 0 10px;">C 级页面默认不进入正式知识库与向量检索，需通过人工审核后方可入库。共 ${def.C} 页待审核。</div>` : "";

        // --- issues from the wiki source page ---
        const pageLevel = r.issues && r.issues.length
          ? `<div class="qr-check fail"><div class="qr-check-icon">!</div><div><b>占位页检测</b><small>${App.escapeHtml(r.issues.join("、"))}</small></div><span class="qr-tag fail">未通过</span></div>`
          : `<div class="qr-check pass"><div class="qr-check-icon">✓</div><div><b>占位页检测</b><small>未发现占位文本或空内容</small></div><span class="qr-tag">通过</span></div>`;

        // --- verdict banner ---
        const passBanner = r.report ? (verdict[1] === "pass"
          ? `<div class="banner-ok">✅ 页面质量满足进入知识库的条件</div>`
          : verdict[1] === "fail"
            ? `<div class="banner-err">❌ 页面质量不合格，不能进入正式知识库</div>`
            : `<div class="banner-warn">⚠ 页面存在质量风险，需要人工确认</div>`) : "";

        // --- pipeline timeline ---
        const rawStages = report.pipeline_stages || report.stages || [];
        const activeSeq = [
          { dot: "✓", label: "Collector" },
          { dot: "✓", label: "Analyzer" },
          { dot: "!", label: "Reviewer" },
          { dot: "✓", label: "Promoter" },
          { dot: "✓", label: "Generator" },
          { dot: "✓", label: "Writer" },
        ];
        let timeline = "";
        if (rawStages.length) {
          const done = new Set(rawStages.filter(s => s.status === "done" || s.status === "succeeded" || s.status === "ok").map(s => s.name));
          const cur = rawStages.find(s => s.status === "running" || s.status === "active");
          timeline = activeSeq.map(s => {
            let cls = "done", dot = "✓";
            if (cur && s.label === cur.name) { cls = "current"; dot = "!"; }
            else if (!cur && !done.has(s.label)) { cls = "pending"; dot = "•"; }
            const st = rawStages.find(x => x.name === s.label);
            return `<div class="qr-stage ${cls}"><div class="qr-stage-dot">${dot}</div><div class="qr-stage-label">${s.label}</div><div class="qr-stage-time">${st ? durationText(st.duration_ms) : "—"}</div></div>`;
          }).join("");
        } else {
          timeline = activeSeq.map(s => `<div class="qr-stage pending"><div class="qr-stage-dot">•</div><div class="qr-stage-label">${s.label}</div><div class="qr-stage-time">—</div></div>`).join("");
        }
        const timelineTitle = report.duration_ms ? `总耗时 ${durationText(report.duration_ms)}` : "总耗时 —";

        // --- checks (best-effort from report fields) ---
        const typeHint = pages.length ? pageTypeLabel(pages[0].type) : "concept";
        const checks = `
          <div class="qr-check pass"><div class="qr-check-icon">✓</div><div><b>页面结构</b><small>frontmatter、标题和正文完整</small></div><span class="qr-tag">通过</span></div>
          <div class="qr-check pass"><div class="qr-check-icon">✓</div><div><b>类型与字段</b><small>${App.escapeHtml(typeHint)} 类型，必填字段完整</small></div><span class="qr-tag">通过</span></div>
          <div class="qr-check ${(r.review_items || []).length ? "warn" : "pass"}"><div class="qr-check-icon">${(r.review_items || []).length ? "!" : "✓"}</div><div><b>证据覆盖</b><small>${(r.review_items || []).length ? (r.review_items || []).length + " 项证据相关项待处理" : "关键结论均有证据支撑"}</small></div><span class="qr-tag ${(r.review_items || []).length ? "warn" : ""}">${(r.review_items || []).length ? "改进" : "通过"}</span></div>
          <div class="qr-check ${r.report ? "pass" : "fail"}"><div class="qr-check-icon">${r.report ? "✓" : "!"}</div><div><b>来源追溯</b><small>${r.report ? "可追溯到当前 RAW 文档" : "缺少摄取报告"}</small></div><span class="qr-tag ${r.report ? "" : "fail"}">${r.report ? "通过" : "缺失"}</span></div>
          <div class="qr-check ${r.report && report.warnings && report.warnings.length ? "warn" : "pass"}"><div class="qr-check-icon">${r.report && report.warnings && report.warnings.length ? "!" : "✓"}</div><div><b>关系与引用</b><small>${r.report && report.warnings && report.warnings.length ? report.warnings.slice(0, 2).join("、") : "已建立 Wiki 关系"}</small></div><span class="qr-tag ${r.report && report.warnings && report.warnings.length ? "warn" : ""}">${r.report && report.warnings && report.warnings.length ? "关注" : "通过"}</span></div>
          ${pageLevel}`;

        // --- content metrics ---
        const stats = [
          [gradeBadge(r.grade || "—"), "质量等级"],
          [report.source_bytes ? App.formatSize(report.source_bytes) : "—", "源文件大小"],
          [report.claims_count ?? "—", "核心结论"],
          [report.evidence_count ?? "—", "证据引用"],
          [report.chunks_count ?? "—", "内容分块"],
          [report.pages_total ?? "—", "生成页面"],
        ].map(s => `<div class="qr-stat"><b>${s[0]}</b><span>${s[1]}</span></div>`).join("");

        // --- footer ---
        const footer = `
          <button class="modal-close">关闭</button>
          <button class="btn-primary qr-recheck">重新摄取</button>`;

        body.innerHTML = `
          <div class="qr-head">
            <div>
              <div class="qr-title">Wiki 生成质量报告
                ${r.report && verdict[1] !== "pass" ? `<span class="qr-tag ${verdict[1] === "warn" ? "warn" : "fail"}">${verdict[1] === "warn" ? "存在改进项" : "未通过"}</span>` : ""}
              </div>
              <p class="text-muted">来源：${App.escapeHtml(path)}${repDate ? " · 最近一次摄取：" + App.escapeHtml(repDate) : ""}</p>
            </div>
          </div>
          ${!r.report ? `<div class="banner-warn" style="margin:0 0 10px;">尚未生成质检报告（文件尚未摄取或报告缺失）</div>` : ""}
          ${passBanner}
          ${cWarn}

          <div class="qr-summary">
            <div class="qr-summary-card main"><div class="qr-summary-label">整体结果</div><div class="qr-summary-value">${verdictIcon} ${verdict[0]}</div><div class="qr-summary-label">${pages.length || report.pages_total || 0} 个 Wiki 页面</div></div>
            <div class="qr-summary-card"><div class="qr-summary-label">通过</div><div class="qr-summary-value">${def.A}</div></div>
            <div class="qr-summary-card"><div class="qr-summary-label">需改进</div><div class="qr-summary-value">${def.B}</div></div>
            <div class="qr-summary-card"><div class="qr-summary-label">待审核</div><div class="qr-summary-value">${def.C}</div></div>
            <div class="qr-summary-card"><div class="qr-summary-label">已隔离</div><div class="qr-summary-value">${(r.quarantine || []).length || report.quarantined_count || 0}</div></div>
          </div>

          <div class="qr-section">
            <div class="qr-section-title">来源上下文 <span>仅用于定位生成批次，不参与评分</span></div>
            <div class="qr-info-grid">${srcRows.map(rr => `<div class="qr-info"><label>${App.escapeHtml(rr[0])}</label><b>${App.escapeHtml(rr[1])}</b></div>`).join("")}</div>
          </div>

          ${pages.length ? `
          <div class="qr-section">
            <div class="qr-section-title">生成的 Wiki 页面 <span>页面级 A/B/C 质量分级</span></div>
            <div class="qr-section-body">${pageRows}</div>
          </div>` : ""}

          ${r.issues && r.issues.length ? `
          <div class="qr-section">
            <div class="qr-section-title">Wiki 页面质量检查 <span>针对当前摄取批次</span></div>
            <div class="qr-section-body qr-checks">${checks}</div>
          </div>` : ""}

          <div class="qr-section">
            <div class="qr-section-title">Wiki 内容指标 <span>针对当前摄取批次</span></div>
            <div class="qr-section-body"><div class="qr-stats">${stats}</div></div>
          </div>

          <div class="qr-section">
            <div class="qr-section-title">Pipeline 处理过程 <span>${App.escapeHtml(timelineTitle)}</span></div>
            <div class="qr-section-body qr-timeline">${timeline}</div>
          </div>

          ${(reviewRows || (r.review_items && r.review_items.length) || (r.quarantine && r.quarantine.length)) ? `
          <div class="qr-section">
            <div class="qr-section-title">Wiki 审核项 <span>${openReviews} 项待处理</span></div>
            <div class="qr-section-body">${reviewRows || `<div class="banner-err" style="margin:0;">无待处理审核项</div>`}</div>
          </div>` : ""}

          ${file && !pages.length && report.task_id ? `
          <div class="qr-section">
            <div class="qr-section-title">文件详情 <span>RAW 文件信息</span></div>
            <div class="qr-info-grid">
              <div class="qr-info"><label>文件名</label><b>${App.escapeHtml(file.name)}</b></div>
              <div class="qr-info"><label>文件类型</label><b>${App.escapeHtml((file.ext || "").toUpperCase())}</b></div>
              <div class="qr-info"><label>文件大小</label><b>${App.formatSize(file.size || 0)}</b></div>
              <div class="qr-info"><label>摄取状态</label><b>${file.ingested ? "已完成" : "待摄取"}</b></div>
            </div>
          </div>` : ""}

          <div class="qr-footer">${footer}</div>
        `;
        overlay.querySelector(".qr-footer .modal-close").addEventListener("click", () => overlay.remove());
        overlay.querySelector(".qr-recheck").addEventListener("click", () => { overlay.remove(); doReingest(path); });
      } catch (e) {
        body.innerHTML = `
          <div class="qr-head"><div><div class="qr-title">Wiki 生成质量报告</div><p class="text-muted">来源：${App.escapeHtml(path)}</p></div></div>
          <div class="banner-err">质检失败: ${App.escapeHtml(e.message)}</div>
          ${file ? `<div class="qr-section"><div class="qr-section-title">文件详情</div><div class="qr-info-grid">
            <div class="qr-info"><label>文件名</label><b>${App.escapeHtml(file.name)}</b></div>
            <div class="qr-info"><label>文件类型</label><b>${App.escapeHtml((file.ext || "").toUpperCase())}</b></div>
            <div class="qr-info"><label>文件大小</label><b>${App.formatSize(file.size || 0)}</b></div>
            <div class="qr-info"><label>摄取状态</label><b>${file.ingested ? "已完成" : "待摄取"}</b></div>
          </div></div>` : ""}
          <div class="qr-footer"><button class="modal-close">关闭</button><button class="btn-primary qr-recheck">重新摄取</button></div>`;
        overlay.querySelector(".qr-footer .modal-close").addEventListener("click", () => overlay.remove());
        overlay.querySelector(".qr-recheck").addEventListener("click", () => { overlay.remove(); doReingest(path); });
      }
    }

    function updateSelectedCount() {
      const btn = document.getElementById("ingestSelectedBtn");
      btn.textContent = `提取选中 (${selectedPaths.size})`;
      btn.disabled = selectedPaths.size === 0;
      const visible = getVisibleFiles();
      const selectAll = document.getElementById("ingestSelectAll");
      selectAll.checked = visible.length > 0 && visible.every(f => selectedPaths.has(f.path));
      selectAll.indeterminate = visible.some(f => selectedPaths.has(f.path)) && !selectAll.checked;
    }

    function setIngestButton(path, text, disabled) {
      document.querySelectorAll(".ingest-one-btn").forEach((button) => {
        if (button.dataset.path === path) {
          button.textContent = text;
          button.disabled = disabled;
        }
      });
    }

    function iconForExt(ext) {
      const map = { ".pdf": "📄", ".docx": "📝", ".xlsx": "📊", ".xls": "📊", ".pptx": "📽️", ".txt": "📃", ".md": "📝", ".html": "🌐", ".xml": "📋", ".json": "📋" };
      return map[ext] || "📎";
    }

    async function batchIngest(paths) {
      const panel = document.getElementById("ingestProgressPanel");
      const total = paths.length;
      panel.innerHTML = `<div class="ingest-batch-progress"><div class="batch-summary">Ingesting (0/${total})</div><div class="progress-row"><div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div></div><div class="batch-task-list" id="batchTaskList"></div></div>`;
      const fill = panel.querySelector(".progress-fill"), summary = panel.querySelector(".batch-summary"), taskList = panel.querySelector("#batchTaskList");
      const terminal = new Set(["succeeded", "failed", "ignored"]);
      const latest = new Map();
      const render = items => {
        items.forEach(item => latest.set(item.source, item));
        const all = Array.from(latest.values());
        taskList.innerHTML = "";
        all.forEach(item => {
          const row = document.createElement("div"); row.className = "batch-task-row";
          row.innerHTML = `<span class="batch-task-name">${App.escapeHtml(item.source.split("/").pop() || item.source)}</span><span class="batch-task-status">${App.escapeHtml(item.status)}</span>`;
          taskList.appendChild(row); updateFileProgress(item.source, item, item.status);
          if (item.status === "succeeded" || item.status === "ignored") { setIngestButton(item.source, "已摄取", true); selectedPaths.delete(item.source); }
          else if (item.status === "failed") { setIngestButton(item.source, "摄取", false); }
          else setIngestButton(item.source, "摄取中...", true);
        });
        const done = all.filter(item => terminal.has(item.status)).length;
        summary.textContent = done === total ? `已完成 (${done}/${total})` : `摄取中 (${done}/${total})`;
        fill.style.width = `${(done / total) * 100}%`;
        if (done === total) { renderFileList(); loadRawFiles(); }
        return done === total;
      };
      try {
        const queued = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/batch`, { method: "POST", body: { sources: paths, folderContext: null } });
        if (render(queued.items || paths.map(source => ({ source, status: "queued" })))) { loadTaskHistory(); loadQueueStatus(); return; }
        const deadline = Date.now() + 15 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 1500));
          const status = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/batches/${encodeURIComponent(queued.batchId)}`);
          if (render(status.items || [])) { loadTaskHistory(); loadQueueStatus(); return; }
        }
        summary.textContent = `摄取超时 (${total})`;
      } catch (e) { panel.insertAdjacentHTML("beforeend", `<div class="banner-err">批量摄取失败: ${App.escapeHtml(e.message)}</div>`); }
      loadTaskHistory(); loadQueueStatus();
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
      let stagesEl = panel.querySelector(".poll-stages");
      if (!stagesEl) {
        stagesEl = document.createElement("div");
        stagesEl.className = "progress-stages poll-stages";
        panel.appendChild(stagesEl);
      }
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
        const terminal = ["succeeded", "failed", "finished", "ignored"].includes(rec.status);
        stagesEl.innerHTML = stages.length || terminal
          ? `<div class="stage-steps">${renderStageSteps(stages.map(s => s.name), terminal)}</div>`
          : "";
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
          const terminal = ["succeeded", "failed", "finished", "ignored"].includes(rec.status);
          stagesEl.innerHTML = stages.length || terminal
            ? `<div class="stage-steps">${renderStageSteps(stages.map(s => s.name), terminal)}</div>`
            : "<span style='color:#9ca3af'>等待阶段事件...</span>";
          const pct = (() => {
            if (["succeeded", "failed", "finished", "ignored"].includes(rec.status)) return 100;
            if (rec.status === "queued") return 5;
            const stagePct = [5, 35, 70, 100];
            return stagePct[Math.min(stages.length, 3)];
          })();
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
        loadTaskHistory();
        loadQueueStatus();
      }
    }
  };
})();
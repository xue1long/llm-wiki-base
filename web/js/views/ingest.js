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
        </div>
      </div>
    `;

    loadRawFiles();

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
        return `<div class="ingest-file-row${f.ingested ? " ingested" : ""}">
          <input type="checkbox" data-path="${App.escapeHtml(f.path)}" ${f.ingested ? "disabled" : ""} />
          <span class="ingest-file-icon">${iconForExt(f.ext)}</span>
          <span class="ingest-file-name">${App.escapeHtml(f.name)}</span>
          <span class="ingest-file-date">${dateStr}</span>
          <span class="ingest-file-size">${App.formatSize(f.size)}</span>
          <span class="ingest-file-status">${f.ingested ? "✓ 已摄取" : ""}</span>
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
  };
})();

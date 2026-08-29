// ruflo-kb — collect view: upload files / URLs / text → Markdown → raw/sources/.
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderCollect = function renderCollect(root) {
    try {
    // 采集页面独立的项目选择（可选不同于全局的项目）
    let collectProjectId = App.state ? App.state.projectId : null;
    const history = []; // 本次会话的采集历史

    root.innerHTML = `
      <div class="collect-page">
        <div class="collect-header">
          <div class="collect-header-left">
            <h2>📥 采集中心</h2>
            <p class="text-muted">将 PDF、文档、链接、图片、文本转换为 Markdown，存入项目的 <code>raw/sources/</code></p>
          </div>
          <div class="collect-header-right" id="collectProjectWrap"></div>
        </div>

        <div class="collect-body">
          <div class="collect-left">
            <!-- 文件上传区 -->
            <div class="collect-section">
              <div class="collect-section-title">📤 上传文件</div>
              <div class="collect-dropzone" id="collectDropzone">
                <div class="collect-dropzone-icon">📄</div>
                <div class="collect-dropzone-text">拖拽文件到此处，或点击选择</div>
                <div class="collect-dropzone-hint">支持 PDF · DOCX · XLSX · HTML · TXT · MD · JPG · PNG · GIF · WebP</div>
                <input type="file" id="collectFileInput" multiple hidden
                  accept=".pdf,.docx,.xlsx,.html,.htm,.txt,.md,.markdown,.jpg,.jpeg,.png,.gif,.webp,.bmp" />
              </div>
              <div class="collect-upload-list" id="collectUploadList"></div>
            </div>

            <!-- URL 采集区 -->
            <div class="collect-section">
              <div class="collect-section-title">🔗 URL 采集</div>
              <div class="collect-url-row">
                <input type="text" id="collectUrlInput" class="collect-url-input"
                  placeholder="https://example.com/article 或 https://.../file.pdf" />
                <button id="collectUrlBtn" class="btn-primary collect-url-btn">采集</button>
              </div>
            </div>

            <!-- 文本粘贴区 -->
            <div class="collect-section">
              <div class="collect-section-title">📝 粘贴文本</div>
              <textarea id="collectTextarea" class="collect-textarea"
                placeholder="在此粘贴或输入文本内容..." rows="6"></textarea>
              <div class="collect-text-footer">
                <input type="text" id="collectTextTitle" class="collect-text-title-input"
                  placeholder="标题（留空则自动提取）" />
                <button id="collectTextBtn" class="btn-primary">采集文本</button>
              </div>
            </div>
          </div>

          <div class="collect-right">
            <!-- 转换预览 -->
            <div class="collect-preview-panel" id="collectPreviewPanel">
              <div class="collect-preview-empty">
                <div class="collect-preview-empty-icon">👁️</div>
                <div>转换预览</div>
                <div class="text-muted">上传文件或输入内容后，此处显示转换结果</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 采集历史 -->
        <div class="collect-history-section">
          <div class="collect-history-header">
            <span class="collect-section-title">📋 采集历史</span>
            <span class="text-muted" id="collectHistoryCount">共 0 条</span>
          </div>
          <div class="collect-history-table-wrap">
            <table class="collect-history-table" id="collectHistoryTable">
              <thead>
                <tr>
                  <th>时间</th><th>来源</th><th>类型</th><th>标题</th><th>大小</th><th>状态</th><th>操作</th>
                </tr>
              </thead>
              <tbody id="collectHistoryBody">
                <tr><td colspan="7" class="collect-history-empty">暂无采集记录</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    // ── 初始化项目下拉框 ──
    const collectHeaderWrap = document.getElementById("collectProjectWrap");
    App.renderProjectSelect(collectHeaderWrap, {
      selectedId: collectProjectId,
      onChange: (id) => {
        collectProjectId = id;
        const proj = (App.state.projects || []).find(p => p.id === id);
        App.toast(`已切换到实例: ${proj ? proj.name : id}`, "info");
      },
      label: "目标实例",
      showNewBtn: false,
    });

    // ── 事件绑定 ──
    setupDropzone();
    setupUrlInput();
    setupTextInput();

    // ── 文件上传 ──
    function setupDropzone() {
      const zone = document.getElementById("collectDropzone");
      const input = document.getElementById("collectFileInput");

      zone.addEventListener("click", () => input.click());
      input.addEventListener("change", () => handleUpload(input.files));

      zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
      zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
      zone.addEventListener("drop", e => {
        e.preventDefault();
        zone.classList.remove("dragover");
        handleUpload(e.dataTransfer.files);
      });
    }

    async function handleUpload(files) {
      if (!files || !files.length) return;
      if (!collectProjectId) { App.toast("请先选择目标实例", "error"); return; }

      const list = document.getElementById("collectUploadList");
      for (const f of files) {
        const row = createUploadRow(list, f.name);
        try {
          const form = new FormData();
          form.append("file", f);
          const res = await fetch(`/api/v1/projects/${collectProjectId}/collect`, {
            method: "POST",
            body: form,
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || res.statusText);
          }
          const data = await res.json();
          setUploadRowStatus(row, "ok", `✓ ${data.source_type}`);
          addHistory(data, f.name, f.size);
          showPreview(data);
          App.toast(`已采集: ${f.name}`, "success");
        } catch (e) {
          setUploadRowStatus(row, "err", `✗ ${e.message}`);
          addHistory({ status: "error", error: e.message }, f.name, f.size);
          App.toast(`采集失败: ${f.name} — ${e.message}`, "error");
        }
      }
      document.getElementById("collectFileInput").value = "";
    }

    // ── URL 采集 ──
    function setupUrlInput() {
      const btn = document.getElementById("collectUrlBtn");
      const input = document.getElementById("collectUrlInput");

      btn.addEventListener("click", () => doCollectUrl());
      input.addEventListener("keydown", e => { if (e.key === "Enter") doCollectUrl(); });
    }

    async function doCollectUrl() {
      const input = document.getElementById("collectUrlInput");
      const url = input.value.trim();
      if (!url) { App.toast("请输入 URL", "error"); return; }
      if (!collectProjectId) { App.toast("请先选择目标实例", "error"); return; }

      const btn = document.getElementById("collectUrlBtn");
      btn.disabled = true; btn.textContent = "采集中...";
      const list = document.getElementById("collectUploadList");
      const row = createUploadRow(list, url);

      try {
        const data = await App.api(`/api/v1/projects/${collectProjectId}/collect-url`, {
          method: "POST",
          body: { url },
        });
        setUploadRowStatus(row, "ok", `✓ ${data.source_type}`);
        addHistory(data, url, 0);
        showPreview(data);
        input.value = "";
        App.toast(`已采集: ${data.title || url}`, "success");
      } catch (e) {
        setUploadRowStatus(row, "err", `✗ ${e.message}`);
        addHistory({ status: "error", error: e.message }, url, 0);
        App.toast(`采集失败: ${e.message}`, "error");
      } finally {
        btn.disabled = false; btn.textContent = "采集";
      }
    }

    // ── 文本采集 ──
    function setupTextInput() {
      const btn = document.getElementById("collectTextBtn");
      btn.addEventListener("click", () => doCollectText());
    }

    async function doCollectText() {
      const textarea = document.getElementById("collectTextarea");
      const titleInput = document.getElementById("collectTextTitle");
      const text = textarea.value.trim();
      if (!text) { App.toast("请输入文本内容", "error"); return; }
      if (!collectProjectId) { App.toast("请先选择目标实例", "error"); return; }

      const btn = document.getElementById("collectTextBtn");
      btn.disabled = true; btn.textContent = "采集中...";
      const filename = (titleInput.value.trim() || text.split("\n")[0].trim().slice(0, 50) || "untitled") + ".txt";

      const list = document.getElementById("collectUploadList");
      const row = createUploadRow(list, filename);

      try {
        // 文本采集通过上传文件实现（构造 File 对象）
        const blob = new Blob([text], { type: "text/plain" });
        const file = new File([blob], filename, { type: "text/plain" });
        const form = new FormData();
        form.append("file", file);

        const res = await fetch(`/api/v1/projects/${collectProjectId}/collect`, {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || res.statusText);
        }
        const data = await res.json();
        setUploadRowStatus(row, "ok", `✓ ${data.source_type}`);
        addHistory(data, filename, blob.size);
        showPreview(data);
        textarea.value = "";
        titleInput.value = "";
        App.toast(`已采集: ${data.title || filename}`, "success");
      } catch (e) {
        setUploadRowStatus(row, "err", `✗ ${e.message}`);
        addHistory({ status: "error", error: e.message }, filename, 0);
        App.toast(`采集失败: ${e.message}`, "error");
      } finally {
        btn.disabled = false; btn.textContent = "采集文本";
      }
    }

    // ── 上传行 UI ──
    function createUploadRow(list, name) {
      const row = document.createElement("div");
      row.className = "collect-upload-row";
      row.innerHTML = `<span class="collect-upload-name">${App.escapeHtml(name)}</span><span class="collect-upload-status"><span class="spinner-sm"></span>转换中...</span>`;
      list.prepend(row);
      return row;
    }

    function setUploadRowStatus(row, cls, text) {
      const st = row.querySelector(".collect-upload-status");
      st.className = `collect-upload-status ${cls}`;
      st.textContent = text;
    }

    // ── 预览面板 ──
    function showPreview(data) {
      const panel = document.getElementById("collectPreviewPanel");
      const projName = (App.state.projects || []).find(p => p.id === collectProjectId)?.name || "";

      panel.innerHTML = `
        <div class="collect-preview-header">
          <div class="collect-preview-title">${App.escapeHtml(data.title || "无标题")}</div>
          <div class="collect-preview-meta">
            <span class="collect-preview-badge">${App.escapeHtml(data.source_type)}</span>
            <span class="text-muted">→ ${App.escapeHtml(data.raw_path)}</span>
          </div>
          <div class="collect-preview-meta">
            <span class="text-muted">实例: ${App.escapeHtml(projName)}</span>
          </div>
        </div>
        <div class="collect-preview-tabs">
          <button class="collect-preview-tab active" data-tab="rendered">预览</button>
          <button class="collect-preview-tab" data-tab="source">源码</button>
        </div>
        <div class="collect-preview-body" id="collectPreviewBody">
          <div class="collect-preview-rendered">${App.renderMd("(加载中...)")}</div>
        </div>
        <div class="collect-preview-actions">
          <button class="btn-primary collect-ingest-btn" id="collectIngestBtn">📥 立即摄取（进入 LLM Pipeline）</button>
          <button class="collect-browse-btn" id="collectBrowseBtn">📂 浏览 raw 文件</button>
        </div>
      `;

      // 加载实际内容
      loadPreviewContent(data.raw_path);

      // Tab 切换
      let currentContent = "";
      panel.querySelectorAll(".collect-preview-tab").forEach(tab => {
        tab.addEventListener("click", () => {
          panel.querySelectorAll(".collect-preview-tab").forEach(t => t.classList.remove("active"));
          tab.classList.add("active");
          const body = document.getElementById("collectPreviewBody");
          if (tab.dataset.tab === "rendered") {
            body.innerHTML = `<div class="collect-preview-rendered">${App.renderMd(currentContent)}</div>`;
          } else {
            body.innerHTML = `<pre class="collect-preview-source">${App.escapeHtml(currentContent)}</pre>`;
          }
        });
      });

      // 立即摄取
      document.getElementById("collectIngestBtn").addEventListener("click", async () => {
        try {
          await App.api(`/api/v1/projects/${collectProjectId}/ingest`, {
            method: "POST",
            body: { source: data.raw_path },
          });
          App.toast("已提交摄取任务", "success");
          App.showView("ingest");
        } catch (e) {
          App.toast("摄取提交失败: " + e.message, "error");
        }
      });

      // 浏览 raw
      document.getElementById("collectBrowseBtn").addEventListener("click", () => {
        App.showView("browse");
      });

      async function loadPreviewContent(rawPath) {
        try {
          const result = await App.api(`/api/v1/projects/${collectProjectId}/files/content?path=${encodeURIComponent(rawPath)}`);
          currentContent = result.content || "";
          const body = document.getElementById("collectPreviewBody");
          body.innerHTML = `<div class="collect-preview-rendered">${App.renderMd(currentContent)}</div>`;
        } catch (e) {
          currentContent = "(无法加载预览)";
          const body = document.getElementById("collectPreviewBody");
          body.innerHTML = `<div class="collect-preview-rendered text-muted">预览加载失败: ${App.escapeHtml(e.message)}</div>`;
        }
      }
    }

    // ── 采集历史 ──
    function addHistory(data, source, size) {
      const now = new Date();
      const time = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
      const ok = data.status === "ok";

      // 推断类型
      let typeLabel = data.source_type || "text";
      const typeMap = { pdf: "PDF", docx: "DOCX", xlsx: "XLSX", html: "HTML", text: "TXT", md: "MD", image: "图片", url: "URL" };
      typeLabel = typeMap[typeLabel] || typeLabel;

      history.unshift({
        time, source, type: typeLabel, title: data.title || "—",
        size: size || 0, status: ok ? "ok" : "err", rawPath: data.raw_path || "",
        projectId: collectProjectId,
      });
      renderHistory();
    }

    function renderHistory() {
      const body = document.getElementById("collectHistoryBody");
      const countEl = document.getElementById("collectHistoryCount");
      countEl.textContent = `共 ${history.length} 条`;

      if (!history.length) {
        body.innerHTML = `<tr><td colspan="7" class="collect-history-empty">暂无采集记录</td></tr>`;
        return;
      }

      body.innerHTML = history.map((h, i) => {
        const projName = (App.state.projects || []).find(p => p.id === h.projectId)?.name || "";
        const statusIcon = h.status === "ok" ? "✅" : "❌";
        const sizeStr = h.size > 0 ? App.formatSize(h.size) : "—";
        return `<tr class="collect-history-row ${h.status === "ok" ? "" : "err"}">
          <td>${App.escapeHtml(h.time)}</td>
          <td class="collect-history-source" title="${App.escapeHtml(h.source)}">${App.escapeHtml(truncate(h.source, 30))}</td>
          <td><span class="collect-history-type">${App.escapeHtml(h.type)}</span></td>
          <td>${App.escapeHtml(truncate(h.title, 25))}</td>
          <td>${App.escapeHtml(sizeStr)}</td>
          <td>${statusIcon}</td>
          <td>
            ${h.status === "ok" ? `<button class="btn-sm collect-preview-btn" data-idx="${i}">预览</button>` : ""}
            <span class="text-muted collect-history-instance" title="${App.escapeHtml(h.projectId)}">${App.escapeHtml(projName)}</span>
          </td>
        </tr>`;
      }).join("");

      // 预览按钮
      body.querySelectorAll(".collect-preview-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          const h = history[Number(btn.dataset.idx)];
          if (h && h.rawPath) {
            showPreview({ title: h.title, source_type: h.type.toLowerCase(), raw_path: h.rawPath });
          }
        });
      });
    }

    function truncate(s, max) {
      return s && s.length > max ? s.slice(0, max) + "…" : s || "";
    }
    } catch (e) {
      root.innerHTML = '<div class="card" style="color:var(--danger-text);padding:20px;"><h3>采集页面加载出错</h3><pre>' + (e.stack || e.message || String(e)) + '</pre></div>';
      console.error("[collect]", e);
    }
  };
})();

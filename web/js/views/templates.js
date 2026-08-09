// ruflo-kb — 模板管理视图 (Templates View)
// 可视化查看/编辑/重置页面模板，支持差异对比。
(() => {
  "use strict";

  const BASE = () => `/api/v1/projects/${App.state.projectId}`;
  const TYPES = ["concept", "entity", "source", "synthesis"];
  let currentType = "concept";

  App.renderTemplates = function renderTemplates(container) {
    container.innerHTML = `
      <div class="card">
        <div class="card-header">
          <h3>模板管理</h3>
          <div class="template-toolbar">
            <button class="btn-sm" id="templateRefreshBtn">刷新</button>
          </div>
        </div>
        <div class="template-type-tabs">
          ${TYPES.map(t => `<button class="template-tab${t === currentType ? ' active' : ''}" data-type="${t}">${t}</button>`).join("")}
        </div>
        <div id="templateInfo" class="template-info"><div class="skeleton skeleton-line"></div></div>
        <div id="templatePreview" class="template-preview"><div class="skeleton skeleton-line"></div></div>
        <div id="templateActions" class="template-actions"></div>
        <div id="templateDiff" class="template-diff" style="display:none;"></div>
      </div>
    `;

    // Tab switching
    container.querySelectorAll(".template-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        container.querySelectorAll(".template-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        currentType = tab.dataset.type;
        loadTemplate(currentType);
      });
    });

    loadTemplate(currentType);
    document.getElementById("templateRefreshBtn").addEventListener("click", () => loadTemplate(currentType));
  };

  async function loadTemplate(typeName) {
    const infoEl = document.getElementById("templateInfo");
    const previewEl = document.getElementById("templatePreview");
    const actionsEl = document.getElementById("templateActions");
    const diffEl = document.getElementById("templateDiff");
    diffEl.style.display = "none";

    try {
      const t = await App.api(`${BASE()}/templates/${typeName}`);
      const sourceLabel = { bundled: "内置默认", user: "用户自定义", project: "项目自定义" }[t.source] || t.source;
      infoEl.innerHTML = `
        <div class="template-meta">
          <span><strong>类型:</strong> ${App.escapeHtml(t.type)}</span>
          <span><strong>版本:</strong> ${App.escapeHtml(t.version)}</span>
          <span><strong>来源:</strong> ${sourceLabel}</span>
        </div>
      `;
      previewEl.innerHTML = `<pre class="template-code">${App.escapeHtml(t.content)}</pre>`;

      const isCustom = t.source === "project" || t.source === "user";
      actionsEl.innerHTML = `
        <button class="btn-sm" id="templateEditBtn">${isCustom ? "编辑" : "自定义"}</button>
        ${isCustom ? `<button class="btn-sm" id="templateResetBtn">重置为默认</button>` : ""}
        <button class="btn-sm" id="templateDiffBtn">对比差异</button>
      `;

      document.getElementById("templateEditBtn").addEventListener("click", () => editTemplate(typeName, t.content));
      if (isCustom) {
        document.getElementById("templateResetBtn").addEventListener("click", () => resetTemplate(typeName));
      }
      document.getElementById("templateDiffBtn").addEventListener("click", () => showDiff(typeName));

    } catch (e) {
      infoEl.innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)}</div>`;
      previewEl.innerHTML = "";
      actionsEl.innerHTML = "";
    }
  }

  async function editTemplate(typeName, currentContent) {
    const newContent = window.prompt(`编辑 ${typeName} 模板内容：`, currentContent);
    if (!newContent || newContent.trim() === currentContent.trim()) return;

    try {
      const r = await App.api(`${BASE()}/templates/${typeName}`, {
        method: "POST",
        body: { content: newContent },
      });
      if (r.ok) {
        App.toast("模板已保存", "success");
        loadTemplate(typeName);
      }
    } catch (e) {
      App.toast(`保存失败: ${e.message}`, "error");
    }
  }

  async function resetTemplate(typeName) {
    if (!confirm(`确认重置 ${typeName} 模板为默认？当前自定义内容将被备份。`)) return;
    try {
      const r = await App.api(`${BASE()}/templates/${typeName}/reset`, { method: "POST" });
      if (r.ok) {
        App.toast("模板已重置为默认", "success");
        loadTemplate(typeName);
      }
    } catch (e) {
      App.toast(`重置失败: ${e.message}`, "error");
    }
  }

  async function showDiff(typeName) {
    const diffEl = document.getElementById("templateDiff");
    try {
      const r = await App.api(`${BASE()}/templates/${typeName}/diff`);
      if (r.note === "no project override") {
        diffEl.innerHTML = `<div class="template-diff-content">(无自定义覆盖，使用内置默认模板)</div>`;
      } else if (!r.diff || !r.diff.length) {
        diffEl.innerHTML = `<div class="template-diff-content">(自定义模板与内置模板内容一致)</div>`;
      } else {
        diffEl.innerHTML = `<h4 style="font-size:13px;margin:8px 0;">差异对比</h4><pre class="template-diff-content">${r.diff.map(line => {
          if (line.startsWith("+")) return `<span class="diff-add">${App.escapeHtml(line)}</span>`;
          if (line.startsWith("-")) return `<span class="diff-remove">${App.escapeHtml(line)}</span>`;
          if (line.startsWith("@")) return `<span class="diff-hunk">${App.escapeHtml(line)}</span>`;
          return App.escapeHtml(line);
        }).join("")}</pre>`;
      }
      diffEl.style.display = "block";
    } catch (e) {
      diffEl.innerHTML = `<div class="banner-err">差异加载失败: ${App.escapeHtml(e.message)}</div>`;
      diffEl.style.display = "block";
    }
  }
})();
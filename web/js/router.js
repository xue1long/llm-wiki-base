// ruflo-kb — state, routing, project management.
(() => {
  "use strict";

  window.App = window.App || {};

  // ---------- Module state ----------
  App.state = {
    projectId: null,
    projectName: null,
    sessionId: null,
    currentView: "search",
    pendingBrowseTarget: null,
    rawFiles: [],
    agentSessionId: null,
    agentAvailable: false,
    agentBusy: false,
    projects: [],
  };

  // ---------- View router ----------
  App.showView = function showView(name) {
    App.state.currentView = name;
    document.querySelectorAll(".nav-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.view === name);
    });
    App.setBanner("");
    App.updateBreadcrumb();
    const content = document.getElementById("content");
    content.innerHTML = "";
    if (!App.state.projectId && name !== "status") {
      content.innerHTML = `<div class="card">需要先注册项目。</div>`;
      return;
    }
    const fn = { search: App.renderSearch, browse: App.renderBrowse, ingest: App.renderIngest, collect: App.renderCollect, chat: App.renderChat, graph: App.renderGraph, heat: App.renderHeat, templates: App.renderTemplates, status: App.renderStatus, settings: App.renderSettings }[name];
    if (fn) fn(content);
  };

  // ---------- Breadcrumb ----------
  App.updateBreadcrumb = function updateBreadcrumb(path) {
    const bc = document.getElementById("breadcrumb");
    const view = App.state.currentView;
    const labels = { search: "搜索", browse: "浏览", ingest: "摄取", collect: "采集", chat: "对话", graph: "图谱", heat: "热度", templates: "模板", status: "状态", settings: "设置" };
    let html = `<a data-nav="search">ruflo-kb</a>`;
    if (view !== "search") {
      html += `<span class="breadcrumb-sep">/</span><a data-nav="${view}">${labels[view] || view}</a>`;
    }
    if (path) {
      const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
      for (let i = 0; i < parts.length; i++) {
        html += `<span class="breadcrumb-sep">/</span>`;
        if (i === parts.length - 1) {
          html += `<span>${App.escapeHtml(parts[i].replace(/\.md$/, ""))}</span>`;
        } else {
          html += `<span>${App.escapeHtml(parts[i])}</span>`;
        }
      }
    }
    bc.innerHTML = html;
    bc.querySelectorAll("a[data-nav]").forEach(a => {
      a.addEventListener("click", () => App.showView(a.dataset.nav));
    });
  };

  // ---------- Toast ----------
  App.toast = function toast(message, type) {
    let container = document.getElementById("toastContainer");
    if (!container) {
      container = document.createElement("div");
      container.id = "toastContainer";
      container.className = "toast-container";
      document.body.appendChild(container);
    }
    const el = document.createElement("div");
    el.className = "toast " + (type || "success");
    el.innerHTML = `<span>${App.escapeHtml(message)}</span><button class="toast-close">&times;</button>`;
    el.querySelector(".toast-close").addEventListener("click", () => el.remove());
    container.appendChild(el);
    setTimeout(() => { if (el.isConnected) el.remove(); }, 3000);
  };

  // ---------- In-page project selector (shared by ingest / browse / collect) ----------
  // Renders a <select> into the given container and returns the select element.
  // When the user picks a different project, calls onChange(projectId).
  App.renderProjectSelect = function renderProjectSelect(container, opts) {
    const { selectedId, onChange, label, showNewBtn } = Object.assign({ selectedId: App.state.projectId, onChange: null, label: "目标实例", showNewBtn: false }, opts || {});
    const projects = App.state.projects || [];
    const wrap = document.createElement("div");
    wrap.className = "page-project-selector";
    wrap.innerHTML = `
      <label class="page-project-label">${App.escapeHtml(label)}</label>
      <select class="page-project-select"></select>
      ${showNewBtn ? '<button class="btn-sm page-project-new-btn" title="新建项目">+ 新建</button>' : ''}
    `;
    container.appendChild(wrap);
    const sel = wrap.querySelector("select");
    sel.innerHTML = projects.map(p =>
      `<option value="${App.escapeHtml(p.id)}" ${p.id === selectedId ? "selected" : ""}>${App.escapeHtml(p.name)} — ${App.escapeHtml(p.path || "")}</option>`
    ).join("");
    sel.addEventListener("change", () => {
      if (onChange) onChange(sel.value);
    });
    if (showNewBtn) {
      wrap.querySelector(".page-project-new-btn").addEventListener("click", async () => {
        const name = window.prompt("输入项目名称：");
        if (!name || !name.trim()) return;
        try {
          const data = await App.api("/api/v1/scenario-templates");
          const templates = data.templates || [];
          const choices = templates.map((t, i) => `${i + 1}. ${t.icon || ""}${t.name}`).join("\n");
          const selected = window.prompt(`选择知识库模板（输入编号，默认 1）：\n${choices}`, "1");
          const index = Math.max(1, Number.parseInt(selected || "1", 10)) - 1;
          const chosen = templates[index] || templates[0];
          await App.createNewProject(name.trim(), chosen && chosen.id);
          // refresh select
          sel.innerHTML = App.state.projects.map(p =>
            `<option value="${App.escapeHtml(p.id)}" ${p.id === App.state.projectId ? "selected" : ""}>${App.escapeHtml(p.name)} — ${App.escapeHtml(p.path || "")}</option>`
          ).join("");
          if (onChange) onChange(App.state.projectId);
        } catch (e) {
          App.setBanner("创建失败: " + e.message, "err");
        }
      });
    }
    return sel;
  };

  // ---------- Project switch (public) ----------
  App.switchProject = async function switchProject(id) {
    const chosen = App.state.projects.find(p => p.id === id);
    if (!chosen) return;
    App.state.projectId = chosen.id;
    App.state.projectName = chosen.name;
    App.state.sessionId = null;
    App.state.pendingBrowseTarget = null;
    try {
      await App.api(`/api/v1/projects/${id}/select`, { method: "POST" });
    } catch (e) { /* non-fatal */ }
  };

  // ---------- New project (public) ----------
  App.createNewProject = async function createNewProject(name, template) {
    const result = await App.api("/api/v1/projects", {
      method: "POST",
      body: { name, template },
    });
    const newProject = { id: result.id, name: result.name, path: result.path, last_opened: Date.now() };
    App.state.projects.unshift(newProject);
    App.state.projectId = newProject.id;
    App.state.projectName = newProject.name;
    try {
      await App.api(`/api/v1/projects/${newProject.id}/select`, { method: "POST" });
    } catch (e) { /* non-fatal */ }
    return newProject;
  };

  // ---------- Theme ----------
  function getTheme() {
    return localStorage.getItem("ruflo-theme") || "auto";
  }
  function applyTheme(theme) {
    const root = document.documentElement;
    if (theme === "auto") {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.setAttribute("data-theme", prefersDark ? "dark" : "light");
    } else {
      root.setAttribute("data-theme", theme);
    }
    const btn = document.getElementById("themeToggleBtn");
    if (btn) btn.textContent = theme === "dark" ? "☀️" : theme === "light" ? "🌙" : "🔄";
  }
  function cycleTheme() {
    const current = getTheme();
    const next = { light: "dark", dark: "auto", auto: "light" }[current] || "auto";
    localStorage.setItem("ruflo-theme", next);
    applyTheme(next);
  }
  function initTheme() {
    applyTheme(getTheme());
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (getTheme() === "auto") applyTheme("auto");
    });
  }

  // ---------- Boot ----------
  App.boot = async function boot() {
    try {
      const data = await App.api("/api/v1/projects");
      const list = data.projects || [];
      App.state.projects = list;
      if (!list.length) {
        App.setBanner("未找到已注册项目，请先新建项目", "err");
        return;
      }
      const chosen = list[0];
      App.state.projectId = chosen.id;
      App.state.projectName = chosen.name;

      document.getElementById("newProjectBtn").style.display = "inline-block";
      document.getElementById("newProjectBtn").addEventListener("click", async () => {
        const name = window.prompt("输入项目名称：");
        if (!name || !name.trim()) return;
        try {
          const data = await App.api("/api/v1/scenario-templates");
          const templates = data.templates || [];
          const choices = templates.map((t, i) => `${i + 1}. ${t.icon || ""}${t.name}`).join("\n");
          const selected = window.prompt(`选择知识库模板（输入编号，默认 1）：\n${choices}`, "1");
          const index = Math.max(1, Number.parseInt(selected || "1", 10)) - 1;
          const chosen = templates[index] || templates[0];
          await App.createNewProject(name.trim(), chosen && chosen.id);
          App.showView(App.state.currentView);
        } catch (e) {
          App.setBanner("创建失败: " + e.message, "err");
        }
      });

      try {
        const h = await App.api("/health");
        const ok = h.ok === true;
        const dot = document.getElementById("healthDot");
        dot.classList.add(ok ? "ok" : "bad");
        document.getElementById("healthText").textContent = ok ? `v${h.version || "?"}` : "异常";
      } catch { /* leave grey */ }
      App.showView("search");

      // Sidebar toggle
      document.getElementById("sidebarToggleBtn").addEventListener("click", () => {
        document.getElementById("sidebar").classList.toggle("collapsed");
        const btn = document.getElementById("sidebarToggleBtn");
        btn.textContent = document.getElementById("sidebar").classList.contains("collapsed") ? "▶" : "◀";
      });

      // Theme toggle
      initTheme();
      document.getElementById("themeToggleBtn").addEventListener("click", cycleTheme);
    } catch (e) {
      App.setBanner("启动失败: " + e.message, "err");
    }
  };
})();

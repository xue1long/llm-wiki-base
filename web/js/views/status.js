// ruflo-kb — status dashboard view (2.4: metric cards, health icons, auto-refresh).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderStatus = function renderStatus(root) {
    let refreshTimer = null;
    let countdown = 30;
    let countdownInterval = null;
    let autoRefresh = true;

    root.innerHTML = `
      <div class="status-toolbar">
        <button id="refreshStatusBtn">刷新</button>
        <span class="status-countdown" id="statusCountdown">30s 后自动刷新</span>
        <button id="cancelRefreshBtn" class="btn-sm" style="display:none;">取消自动刷新</button>
      </div>
      <div class="status-metrics" id="statusMetrics">
        <div class="metric-card"><div class="skeleton skeleton-line"></div></div>
        <div class="metric-card"><div class="skeleton skeleton-line"></div></div>
        <div class="metric-card"><div class="skeleton skeleton-line"></div></div>
        <div class="metric-card"><div class="skeleton skeleton-line"></div></div>
      </div>
      <div class="status-grid" id="statusGrid">
        <div class="stat-card">加载中...</div>
      </div>
    `;

    document.getElementById("refreshStatusBtn").addEventListener("click", () => {
      resetCountdown();
      loadAll();
    });
    document.getElementById("cancelRefreshBtn").addEventListener("click", () => {
      autoRefresh = false;
      clearInterval(countdownInterval);
      countdownInterval = null;
      document.getElementById("cancelRefreshBtn").style.display = "none";
      document.getElementById("statusCountdown").textContent = "自动刷新已关闭";
    });

    function resetCountdown() {
      countdown = 30;
      updateCountdownDisplay();
      if (!autoRefresh) {
        autoRefresh = true;
        document.getElementById("cancelRefreshBtn").style.display = "inline-block";
      }
      if (countdownInterval) clearInterval(countdownInterval);
      countdownInterval = setInterval(() => {
        countdown--;
        updateCountdownDisplay();
        if (countdown <= 0) {
          clearInterval(countdownInterval);
          countdownInterval = null;
          countdown = 30;
          loadAll();
        }
      }, 1000);
    }

    function updateCountdownDisplay() {
      document.getElementById("statusCountdown").textContent = countdown + "s 后自动刷新";
    }

    loadAll();

    async function loadAll() {
      const grid = document.getElementById("statusGrid");
      grid.innerHTML = `<div class="stat-card"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div></div>`;

      const tasks = {
        health: App.api("/health").catch(e => ({ __err: e.message })),
        project: App.api(`/api/v1/projects/${App.state.projectId}`).catch(e => ({ __err: e.message })),
        files:   App.api(`/api/v1/projects/${App.state.projectId}/files?root=wiki`).catch(e => ({ __err: e.message })),
        rawFiles: App.api(`/api/v1/projects/${App.state.projectId}/raw-files`).catch(e => ({ __err: e.message })),
        graph:  App.api(`/api/v1/projects/${App.state.projectId}/wiki/graph`).catch(e => ({ __err: e.message })),
        reviews: App.api(`/api/v1/projects/${App.state.projectId}/reviews?status=open`).catch(e => ({ __err: e.message })),
        schema:  App.api(`/api/v1/projects/${App.state.projectId}/schema`).catch(e => ({ __err: e.message })),
        lint:    App.api(`/api/v1/projects/${App.state.projectId}/lint`).catch(e => ({ __err: e.message })),
      };
      const [health, project, files, rawFiles, graph, reviews, schema, lint] = await Promise.all(Object.values(tasks));

      // Metric cards
      const wikiCount = files.__err ? "—" : (files.totalCount ?? "—");
      const rawCount = rawFiles.__err ? "—" : ((rawFiles.files || []).length);
      const graphNodes = graph.__err ? "—" : (graph.counts ? graph.counts.nodes : "—");
      const lintEdges = lint.__err ? "—" : (lint.summary ? lint.summary.edges : "—");

      document.getElementById("statusMetrics").innerHTML = `
        <div class="metric-card">
          <div class="metric-value">${wikiCount}</div>
          <div class="metric-label">Wiki 页面</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">${rawCount}</div>
          <div class="metric-label">原始源文件</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">${graphNodes}</div>
          <div class="metric-label">图谱节点</div>
        </div>
        <div class="metric-card">
          <div class="metric-value">${lintEdges}</div>
          <div class="metric-label">图谱关系</div>
        </div>
      `;

      // Detail cards
      grid.innerHTML = "";

      // Health card with ✓/✗ icons
      const healthOk = !health.__err && health.ok;
      const healthIcon = (cond) => cond ? '<span class="health-icon ok">✓</span>' : '<span class="health-icon bad">✗</span>';
      grid.insertAdjacentHTML("beforeend", statCard("服务健康", [
        ["状态", healthIcon(healthOk) + (health.__err ? " " + App.escapeHtml(health.__err) : (healthOk ? " running" : " unhealthy"))],
        ["version", health.__err ? "—" : (health.version || "—")],
        ["agent.chat", healthIcon(!health.__err && health.agent && health.agent.chat)],
        ["agent.streaming", healthIcon(!health.__err && health.agent && health.agent.streaming)],
      ]));

      grid.insertAdjacentHTML("beforeend", statCard("项目", [
        ["name", project.__err ? "—" : (project.name || "—")],
        ["id", project.__err ? "—" : (project.id || "—")],
        ["path", project.__err ? "—" : (project.path || "—")],
        ["schema_version", project.__err ? "—" : (project.schema_version || "—")],
        ["last_opened", project.__err ? "—" : formatTime(project.last_opened)],
      ]));

      grid.insertAdjacentHTML("beforeend", statCard("统计", [
        ["wiki 页面总数", files.__err ? "—" : (files.totalCount ?? "—")],
        ["待审核数", reviews.__err ? "—" : (reviews.count ?? "—")],
      ]));

      const migrations = (schema.__err || !Array.isArray(schema.schemas)) ? []
        : schema.schemas.map(s => `${s.schema} (${s.from}→${s.to})`);
      grid.insertAdjacentHTML("beforeend", statCard("Schema", [
        ["current", schema.__err ? "—" : (schema.schema_version || "—")],
        ["迁移", schema.__err ? "—" : (migrations.join(", ") || "(无)")],
      ]));

      if (!lint.__err && lint.summary) {
        const s = lint.summary;
        grid.insertAdjacentHTML("beforeend", statCard("Lint (14.5)", [
          ["节点", s.nodes],
          ["关系", s.edges],
          ["孤立页", s.orphans],
          ["悬空引用", s.dangling],
        ]));
        const detail = `<div class="stat-card"><h3>Lint 明细</h3>
          ${lint.orphans && lint.orphans.length ? `
            <div class="lint-section">孤儿页 (${lint.orphans.length})</div>
            <ul class="lint-list">${lint.orphans.slice(0, 8).map(o => `<li><code>${App.escapeHtml(o.id)}</code> — ${App.escapeHtml(o.title || "")}</li>`).join("")}</ul>
          ` : ""}
          ${lint.dangling && lint.dangling.length ? `
            <div class="lint-section">悬空引用 (${lint.dangling.length})</div>
            <ul class="lint-list">${lint.dangling.slice(0, 8).map(d => `<li><code>${App.escapeHtml(d.source)}</code> → <code>${App.escapeHtml(d.target)}</code> (${App.escapeHtml(d.type || "?")})</li>`).join("")}</ul>
          ` : ""}
        </div>`;
        grid.insertAdjacentHTML("beforeend", detail);
      } else if (lint.__err) {
        grid.insertAdjacentHTML("beforeend", statCard("Lint (14.5)", [["错误", lint.__err]]));
      }

      // Start countdown after first load
      if (!refreshTimer) {
        resetCountdown();
      }
    }

    function statCard(title, rows) {
      return `<div class="stat-card"><h3>${App.escapeHtml(title)}</h3>${rows.map(([k, v]) =>
        `<div class="stat-row"><span class="stat-key">${App.escapeHtml(k)}</span><span class="stat-val">${v}</span></div>`
      ).join("")}</div>`;
    }

    function formatTime(ms) {
      if (!ms) return "—";
      try { return new Date(ms).toLocaleString(); } catch { return String(ms); }
    }
  };
})();

// ruflo-kb — 热度管理视图 (Heat View)
// 展示热度分布、热点/冷点/僵尸页面，支持触发衰减、恢复/归档僵尸页。
(() => {
  "use strict";

  const BASE = () => `/api/v1/projects/${App.state.projectId}`;

  App.renderHeat = function renderHeat(container) {
    container.innerHTML = `
      <div class="card">
        <div class="card-header">
          <h3>热度管理</h3>
          <div class="heat-toolbar">
            <button id="heatDecayBtn" class="btn-sm">触发衰减</button>
            <button id="heatRefreshBtn" class="btn-sm">刷新</button>
          </div>
        </div>
        <div id="heatPools" class="heat-pools"><div class="skeleton skeleton-line"></div></div>
        <div id="heatTop" class="heat-top"><h4 style="font-size:13px;margin:12px 0 6px;">最高热度 Top 10</h4><div class="skeleton skeleton-line"></div></div>
        <div id="heatZombies" class="heat-zombies"><h4 style="font-size:13px;margin:12px 0 6px;">僵尸页面</h4><div class="skeleton skeleton-line"></div></div>
      </div>
    `;
    loadHeat();
    document.getElementById("heatRefreshBtn").addEventListener("click", loadHeat);
    document.getElementById("heatDecayBtn").addEventListener("click", doDecay);
  };

  async function loadHeat() {
    const poolsEl = document.getElementById("heatPools");
    const topEl = document.getElementById("heatTop");
    const zombiesEl = document.getElementById("heatZombies");
    try {
      const data = await App.api(`${BASE()}/heat`);
      renderPools(poolsEl, data.pools);
      renderTop(topEl, data.top || []);
      renderZombies(zombiesEl, data.zombies || []);
    } catch (e) {
      poolsEl.innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)} <button class="btn-sm" onclick="loadHeat()">重试</button></div>`;
      topEl.innerHTML = "";
      zombiesEl.innerHTML = "";
    }
  }

  function renderPools(el, pools) {
    if (!pools) {
      el.innerHTML = `<div class="heat-empty">尚无热度数据，请先摄取文档。</div>`;
      return;
    }
    const total = pools.hot + pools.warm + pools.cold + pools.zombie || 1;
    const bars = [
      { label: "🔥 热点 (80-100)", count: pools.hot, color: "#ef4444" },
      { label: "🔆 温点 (40-79)", count: pools.warm, color: "#f59e0b" },
      { label: "❄️ 冷点 (1-39)", count: pools.cold, color: "#3b82f6" },
      { label: "💀 僵尸 (0)", count: pools.zombie, color: "#6b7280" },
    ];
    el.innerHTML = `<div class="heat-distribution">${bars.map(b => `
      <div class="heat-bar-row">
        <span class="heat-bar-label">${b.label}</span>
        <div class="heat-bar-track"><div class="heat-bar-fill" style="width:${(b.count/total*100).toFixed(1)}%;background:${b.color}"></div></div>
        <span class="heat-bar-count">${b.count} 页</span>
      </div>
    `).join("")}</div>`;
  }

  function renderTop(el, top) {
    if (!top.length) {
      el.innerHTML = `<h4 style="font-size:13px;margin:12px 0 6px;">最高热度 Top 10</h4><div class="heat-empty">暂无数据</div>`;
      return;
    }
    el.innerHTML = `<h4 style="font-size:13px;margin:12px 0 6px;">最高热度 Top 10</h4>
      <table class="heat-top-table">
        <thead><tr><th>#</th><th>热度</th><th>类型</th><th>标题</th><th>路径</th></tr></thead>
        <tbody>${top.map(r => `
          <tr class="heat-top-row" data-path="${App.escapeHtml(r.path)}">
            <td>${r.rank}</td>
            <td><span class="heat-badge" style="background:${r.heat >= 80 ? '#ef4444' : r.heat >= 40 ? '#f59e0b' : '#3b82f6'}">${r.heat}</span></td>
            <td><span class="badge badge-${r.type}">${r.type}</span></td>
            <td>${App.escapeHtml(r.title)}</td>
            <td class="heat-path">${App.escapeHtml(r.path)}</td>
          </tr>
        `).join("")}</tbody>
      </table>`;
    el.querySelectorAll(".heat-top-row").forEach(row => {
      row.addEventListener("click", () => {
        App.state.pendingBrowseTarget = row.dataset.path;
        App.showView("browse");
      });
    });
  }

  function renderZombies(el, zombies) {
    if (!zombies.length) {
      el.innerHTML = `<h4 style="font-size:13px;margin:12px 0 6px;">僵尸页面</h4><div class="heat-empty">✅ 无僵尸页面</div>`;
      return;
    }
    const ids = zombies.map(z => App.escapeHtml(z.page_id));
    el.innerHTML = `<h4 style="font-size:13px;margin:12px 0 6px;">僵尸页面</h4>
      <div class="zombie-actions">
        <label><input type="checkbox" id="zombieSelectAll"> 全选</label>
        <button class="btn-sm" id="zombieRestoreBtn">恢复选中</button>
        <button class="btn-sm btn-danger" id="zombieArchiveBtn">归档选中</button>
      </div>
      <div class="zombie-list">${zombies.map(z => `
        <div class="zombie-item">
          <label><input type="checkbox" class="zombie-cb" value="${App.escapeHtml(z.page_id)}">
          💀 <strong>${App.escapeHtml(z.title || z.page_id)}</strong>
          <span class="heat-path">${App.escapeHtml(z.path)}</span>
          <span class="heat-muted">僵尸于 ${z.zombie_since ? new Date(z.zombie_since).toLocaleDateString() : "?"}</span></label>
        </div>
      `).join("")}</div>`;

    document.getElementById("zombieSelectAll").addEventListener("change", e => {
      document.querySelectorAll(".zombie-cb").forEach(cb => cb.checked = e.target.checked);
    });
    document.getElementById("zombieRestoreBtn").addEventListener("click", () => batchZombieAction("restore"));
    document.getElementById("zombieArchiveBtn").addEventListener("click", () => batchZombieAction("archive"));
  }

  async function batchZombieAction(action) {
    const cbs = document.querySelectorAll(".zombie-cb:checked");
    if (!cbs.length) { App.toast("请先选择页面", "warn"); return; }
    const pageIds = Array.from(cbs).map(cb => cb.value);
    const label = action === "restore" ? "恢复" : "归档";
    if (action === "archive" && !confirm(`确认将 ${pageIds.length} 个僵尸页归档到 _archive/？`)) return;

    try {
      const r = await App.api(`${BASE()}/heat/zombies/${action}`, {
        method: "POST",
        body: { page_ids: pageIds },
      });
      App.toast(`已${label} ${r[action === "restore" ? "restored" : "archived"]} 个页面`, "success");
      loadHeat();
    } catch (e) {
      App.toast(`${label}失败: ${e.message}`, "error");
    }
  }

  async function doDecay() {
    if (!confirm("确认触发热度衰减？这将降低所有长期未访问页面的热度。")) return;
    const btn = document.getElementById("heatDecayBtn");
    btn.disabled = true;
    try {
      const r = await App.api(`${BASE()}/heat/decay`, { method: "POST" });
      App.toast(`衰减完成: ${r.decayed} 个页面衰减, ${r.zombies_created} 个变为僵尸`, "success");
      loadHeat();
    } catch (e) {
      App.toast(`衰减失败: ${e.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  }
})();
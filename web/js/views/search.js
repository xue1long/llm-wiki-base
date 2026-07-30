// ruflo-kb — search view (redesigned §1.5).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderSearch = function renderSearch(root) {
    root.innerHTML = `
      <div class="search-bar">
        <input type="text" id="qInput" placeholder="输入搜索关键词..." autofocus />
        <div class="search-type-filter" id="typeFilter">
          <label class="type-radio active"><input type="radio" name="stype" value="" checked />全部</label>
          <label class="type-radio"><input type="radio" name="stype" value="concept" />概念</label>
          <label class="type-radio"><input type="radio" name="stype" value="entity" />实体</label>
          <label class="type-radio"><input type="radio" name="stype" value="source" />来源</label>
          <label class="type-radio"><input type="radio" name="stype" value="synthesis" />综合</label>
        </div>
        <button id="qBtn">搜索</button>
      </div>
      <div id="searchStats" style="display:none;"></div>
      <div id="results"></div>
    `;
    const input = document.getElementById("qInput");
    const btn = document.getElementById("qBtn");
    const trigger = () => doSearch();
    btn.addEventListener("click", trigger);
    input.addEventListener("keydown", e => { if (e.key === "Enter") trigger(); });

    // Type radio styling
    document.querySelectorAll("#typeFilter .type-radio").forEach(label => {
      label.addEventListener("click", () => {
        document.querySelectorAll("#typeFilter .type-radio").forEach(l => l.classList.remove("active"));
        label.classList.add("active");
      });
    });

    async function doSearch() {
      const q = input.value.trim();
      if (!q) { App.setBanner("请输入关键词", "warn"); return; }
      btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> 搜索中...`;
      App.setBanner("");
      const statsEl = document.getElementById("searchStats");
      statsEl.style.display = "none";
      try {
        const selType = document.querySelector("input[name='stype']:checked");
        const body = { query: q, topK: 20, mode: "hybrid" };
        if (selType && selType.value) body.type = selType.value;
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/search`, {
          method: "POST", body,
        });
        renderResults(data.results || [], q, data.tokenHits || 0, data.vectorHits || 0);
      } catch (e) {
        App.setBanner("搜索失败: " + e.message, "err");
        document.getElementById("results").innerHTML = "";
      } finally {
        btn.disabled = false; btn.textContent = "搜索";
      }
    }

    function renderResults(results, query, tokenHits, vectorHits) {
      const out = document.getElementById("results");
      const statsEl = document.getElementById("searchStats");
      const N = results.length;
      let statsHtml = `找到 <strong>${N}</strong> 条结果`;
      if (tokenHits || vectorHits) {
        statsHtml += `（关键词 ${tokenHits}`;
        if (vectorHits > 0) {
          statsHtml += `，语义 ${vectorHits}`;
        } else {
          statsHtml += `，语义 <span style="color:var(--text-muted)">${vectorHits}</span>`;
        }
        statsHtml += `）`;
      }
      statsEl.innerHTML = statsHtml;
      statsEl.style.display = "block";

      if (!results.length) {
        out.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">🔍</div>
          <div class="empty-state-title">没有匹配结果</div>
          <div class="empty-state-desc">尝试换个关键词，或调整类型筛选条件</div>
        </div>`;
        return;
      }
      out.innerHTML = results.map((r, i) => {
        const typeBadge = r.type ? `<span class="badge badge-type badge-type-${r.type}">${App.escapeHtml(r.type)}</span>` : "";
        const sourceBadge = r.source === "semantic"
          ? `<span class="badge badge-semantic">semantic</span>`
          : `<span class="badge badge-keyword">keyword</span>`;
        const displayPath = App.normalizeWikiPath(r.path);
        const snippet = highlightKeywords(App.escapeHtml(r.content || ""), query);
        return `
          <div class="card" data-idx="${i}">
            <div class="card-title">${App.escapeHtml(r.title || displayPath)}</div>
            <div class="card-meta">${typeBadge} ${sourceBadge} <span>score ${(r.score ?? 0).toFixed(3)}</span></div>
            <div class="card-snippet">${snippet}</div>
            <div class="card-path">${App.escapeHtml(displayPath)}</div>
            <div class="fulltext" id="ft-${i}" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);"></div>
          </div>
        `;
      }).join("");
      out.querySelectorAll(".card").forEach(card => {
        card.addEventListener("click", async (ev) => {
          if (ev.target.closest(".fulltext")) return;
          const idx = card.dataset.idx;
          const ft = document.getElementById(`ft-${idx}`);
          if (!ft) return;
          if (ft.style.display !== "none") { ft.style.display = "none"; return; }
          const path = results[idx].path;
          ft.innerHTML = `<div class="skeleton skeleton-line"></div>`;
          ft.style.display = "block";
          try {
            const stripped = App.normalizeWikiPath(path);
            const fc = await App.api(`/api/v1/projects/${App.state.projectId}/files/content?path=${encodeURIComponent(stripped)}`);
            const { fm, body } = App.parseFrontmatter(fc.content || "");
            ft.innerHTML = App.renderFrontmatter(fm) + `<div class="reader-body">${App.renderMd(body)}</div>`;
          } catch (e) {
            ft.innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)}</div>`;
          }
        });
      });
    }

    function highlightKeywords(text, query) {
      if (!query || !text) return text;
      const words = query.split(/\s+/).filter(w => w.length > 0);
      let result = text;
      for (const w of words) {
        const escaped = w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        result = result.replace(new RegExp(`(${escaped})`, "gi"), "<mark>$1</mark>");
      }
      return result;
    }
  };
})();

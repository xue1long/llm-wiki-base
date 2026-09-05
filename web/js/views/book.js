// ruflo-kb — Book view: one-click build of the KC Book view, with the
// read-only Wiki reader kept as the fallback for projects that have no
// Knowledge Compiler data yet.
//
// Two surfaces share this page:
//   * Build panel  -> GET  /api/v1/kc/book/status
//                     POST /api/v1/kc/book/build   (dry-run by default)
//   * Reader pane  -> the integrity-verified read-only Wiki-to-Book release
//
// The build is dry-run by default on purpose: a book build touches every
// claim in the project. "预览构建" proves the plan first; only the explicit
// "生成并写入磁盘" button writes anything.
(() => {
  "use strict";

  window.App = window.App || {};

  const VOLUMES = [
    ["all", "全部"], ["sources", "Sources"], ["concepts", "Concepts"],
    ["entities", "Entities"], ["synthesis", "Synthesis"],
  ];

  App.renderBook = function renderBook(root) {
    let files = [];
    let book = null;
    let selectedVolume = "all";
    let query = "";
    let busy = false;
    let canBuild = false;

    root.innerHTML = `
      <section class="book-shell">
        <div class="book-hero">
          <div>
            <div class="book-kicker">KNOWLEDGE BOOK · LIVE WIKI</div>
            <h1>把 Wiki 读成一本书</h1>
            <p>左侧目录按 Wiki 类型整理当前实例（只读）。若该项目已有 Knowledge Compiler 数据，可在下方一键编译生成 Book 视图。</p>
          </div>
          <div class="book-stats" id="bookStats">加载中…</div>
        </div>
        <div class="book-build">
          <div class="book-build-status" id="bookBuildStatus">正在读取 Book 状态…</div>
          <div class="book-build-actions">
            <button class="btn-sm" id="bookStatusBtn">刷新状态</button>
            <button class="btn-sm" id="bookDryRunBtn" disabled>预览构建</button>
            <button class="btn-sm btn-primary" id="bookApplyBtn" disabled>生成并写入磁盘</button>
          </div>
          <div id="bookBuildResult"></div>
        </div>
        <div class="book-toolbar">
          <div class="book-volumes" id="bookVolumes"></div>
          <select id="bookVersionSelect" class="book-version-select" aria-label="选择 Book 版本" disabled>
            <option>加载 Book 版本…</option>
          </select>
          <input id="bookSearch" class="book-search" placeholder="搜索章节标题…" aria-label="搜索章节标题" />
        </div>
        <div class="book-layout">
          <aside class="book-toc" id="bookToc"><div class="skeleton skeleton-line"></div></aside>
          <article class="book-reader" id="bookReader">
            <div class="book-reader-empty"><span>✦</span><h2>选择一页开始阅读</h2><p>左侧目录会按 Wiki 类型整理当前实例。</p></div>
          </article>
          <aside class="book-info" id="bookInfo"><div class="skeleton skeleton-line"></div></aside>
        </div>
      </section>`;

    const toc = root.querySelector("#bookToc");
    const reader = root.querySelector("#bookReader");
    const info = root.querySelector("#bookInfo");
    const stats = root.querySelector("#bookStats");
    const volumeBar = root.querySelector("#bookVolumes");
    const versionSelect = root.querySelector("#bookVersionSelect");
    const search = root.querySelector("#bookSearch");
    const buildStatusEl = root.querySelector("#bookBuildStatus");
    const buildResultEl = root.querySelector("#bookBuildResult");
    const statusBtn = root.querySelector("#bookStatusBtn");
    const dryRunBtn = root.querySelector("#bookDryRunBtn");
    const applyBtn = root.querySelector("#bookApplyBtn");

    volumeBar.innerHTML = VOLUMES.map(([id, label]) =>
      `<button class="book-volume${id === selectedVolume ? " active" : ""}" data-volume="${id}">${label}</button>`
    ).join("");
    volumeBar.addEventListener("click", event => {
      const button = event.target.closest("[data-volume]");
      if (!button) return;
      selectedVolume = button.dataset.volume;
      volumeBar.querySelectorAll(".book-volume").forEach(el => el.classList.toggle("active", el === button));
      renderToc();
    });
    search.addEventListener("input", () => { query = search.value.trim().toLowerCase(); renderToc(); });
    versionSelect.addEventListener("change", () => loadBook(versionSelect.value));

    statusBtn.addEventListener("click", () => { loadStatus(); });
    dryRunBtn.addEventListener("click", () => { runBuild(false); });
    applyBtn.addEventListener("click", () => { runBuild(true); });

    // ---------- Build panel ----------

    function syncButtons() {
      statusBtn.disabled = busy;
      dryRunBtn.disabled = busy || !canBuild;
      applyBtn.disabled = busy || !canBuild;
    }

    function showResult(kind, html) {
      buildResultEl.innerHTML = `<div class="book-build-result ${kind}">${html}</div>`;
    }

    function clearResult() {
      buildResultEl.innerHTML = "";
    }

    function joinCodes(codes) {
      return App.escapeHtml((codes || []).join(", ") || "未知");
    }

    async function loadStatus() {
      buildStatusEl.textContent = "正在读取 Book 状态…";
      try {
        const data = await App.api(
          `/api/v1/kc/book/status?project_id=${encodeURIComponent(App.state.projectId)}`
        );
        canBuild = !data.empty;
        if (data.empty) {
          buildStatusEl.innerHTML = `<strong>暂无可构建的 KC 数据</strong>
            <div class="book-build-meta">原因：${joinCodes(data.reason_codes)}。左侧仍可只读浏览 Wiki。</div>`;
        } else {
          buildStatusEl.innerHTML =
            `<strong>${data.chapters} 章 · ${data.claims} claims · ${data.evidence} evidence</strong>
             <div class="book-build-meta">publication_version=${App.escapeHtml(String(data.publication_version))}` +
            `${data.derived ? " · 按来源文档派生（derived）" : ""} · 产物写入项目根 book/ 目录</div>`;
        }
      } catch (error) {
        canBuild = false;
        buildStatusEl.innerHTML = `<strong>Book 状态不可用</strong>
          <div class="book-build-meta">${App.escapeHtml(error.message)} — 已降级为只读 Wiki 浏览。</div>`;
      }
      syncButtons();
    }

    async function runBuild(apply) {
      if (busy) return;
      busy = true;
      syncButtons();
      clearResult();
      buildStatusEl.textContent = apply ? "正在生成并写入…" : "正在预览构建…";
      try {
        const data = await App.api("/api/v1/kc/book/build", {
          method: "POST",
          body: { project_id: App.state.projectId, apply: apply },
        });
        if (data.status === "empty") {
          showResult("warn", `没有可构建的内容：${joinCodes(data.reason_codes)}`);
        } else if (data.status === "planned") {
          showResult("ok", `预览完成：<strong>${data.chapter_count}</strong> 章可编译，未写入磁盘。确认无误后点「生成并写入磁盘」。`);
        } else {
          showResult("ok", `已生成 <strong>${data.chapter_count}</strong> 章 → <code>${App.escapeHtml(String(data.output_dir || ""))}</code>`);
        }
      } catch (error) {
        showResult("err", App.escapeHtml(error.message));
      } finally {
        busy = false;
        await loadStatus();
      }
    }

    // ---------- Read-only Wiki-to-Book reader ----------

    async function loadBook(version = "") {
      const query = version ? `?version=${encodeURIComponent(version)}` : "";
      try {
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/book-wiki${query}`);
        book = data;
        files = data.chapters || [];
        stats.textContent = `${files.length.toLocaleString()} 章 · ${(data.page_count || 0).toLocaleString()} 页`;
        renderBookInfo();
        renderToc();
      } catch (error) {
        book = null;
        stats.textContent = "加载失败";
        toc.innerHTML = `<div class="banner-err">Book 加载失败：${App.escapeHtml(error.message)}</div>`;
        info.innerHTML = `<div class="book-info-empty">当前没有可预览的激活版本</div>`;
      }
    }

    async function loadVersions() {
      try {
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/book-wiki/versions`);
        const versions = data.versions || [];
        if (!versions.length) {
          versionSelect.innerHTML = "<option>暂无可用 Book 版本</option>";
          return;
        }
        versionSelect.innerHTML = versions.map(item => {
          const label = `${String(item.version).slice(0, 12)} · ${Number(item.chapter_count || 0).toLocaleString()}章 · ${Number(item.page_count || 0).toLocaleString()}页${item.active ? " · 当前" : ""}`;
          return `<option value="${App.escapeHtml(String(item.version))}">${App.escapeHtml(label)}</option>`;
        }).join("");
        versionSelect.disabled = false;
        const active = versions.find(item => item.active) || versions[0];
        versionSelect.value = active.version;
        await loadBook(active.version);
      } catch (error) {
        versionSelect.innerHTML = "<option>版本列表不可用</option>";
        await loadBook();
      }
    }

    function volumeFor(chapter) {
      const raw = typeof chapter === "string"
        ? chapter
        : (chapter.chapter_id || chapter.path || "");
      const prefix = String(raw).split(/[\\/]/).pop().split("-", 1)[0];
      const volumes = { source: "sources", concept: "concepts", entity: "entities", synthesis: "synthesis" };
      return volumes[prefix] || "chapters";
    }

    function renderToc() {
      const filtered = files.filter(file => {
        const volume = volumeFor(file);
        const title = file.title || file.chapter_id || file.path;
        return (selectedVolume === "all" || volume === selectedVolume) && (!query || title.toLowerCase().includes(query));
      });
      const grouped = new Map();
      for (const file of filtered) {
        const volume = volumeFor(file);
        if (!grouped.has(volume)) grouped.set(volume, []);
        grouped.get(volume).push(file);
      }
      const labels = { sources: "Sources · 来源", concepts: "Concepts · 概念", entities: "Entities · 实体", synthesis: "Synthesis · 综合", chapters: "章节" };
      if (!filtered.length) {
        toc.innerHTML = `<div class="book-empty">没有匹配的章节</div>`;
        return;
      }
      toc.innerHTML = Array.from(grouped, ([volume, items]) => `
        <section class="book-volume-group">
          <div class="book-volume-heading">${labels[volume]} <span>${items.length}</span></div>
          ${items.slice(0, 300).map(file => {
            const title = file.title || file.chapter_id || file.path;
            return `<button class="book-chapter" data-path="${App.escapeHtml(file.path)}">${App.escapeHtml(title)}</button>`;
          }).join("")}
          ${items.length > 300 ? `<div class="book-more">还有 ${items.length - 300} 页，请继续搜索</div>` : ""}
        </section>`).join("");
      toc.querySelectorAll(".book-chapter").forEach(button => button.addEventListener("click", () => loadPage(button)));
      if (!toc.querySelector(".book-chapter.active")) toc.querySelector(".book-chapter")?.click();
    }

    async function loadPage(button) {
      toc.querySelectorAll(".book-chapter").forEach(el => el.classList.toggle("active", el === button));
      reader.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div>`;
      try {
        const params = new URLSearchParams({path: button.dataset.path});
        if (versionSelect.value && !versionSelect.disabled) params.set("version", versionSelect.value);
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/book-wiki/content?${params}`);
        const title = button.textContent;
        const chapter = files.find(item => item.path === button.dataset.path);
        reader.innerHTML = `<div class="book-reader-kicker">${App.escapeHtml(volumeFor(chapter || {}))} · WIKI-TO-BOOK</div>
          <h2>${App.escapeHtml(title)}</h2><div class="reader-body">${App.renderMd(data.content || "")}</div>`;
        renderChapterInfo(chapter, data);
        App.updateBreadcrumb(`book-wiki/${button.dataset.path}`);
      } catch (error) {
        reader.innerHTML = `<div class="banner-err">章节读取失败：${App.escapeHtml(error.message)}</div>`;
      }
    }

    function renderBookInfo() {
      if (!book) return;
      info.innerHTML = `<div class="book-info-eyebrow">ACTIVE RELEASE</div>
        <div class="book-info-title">${App.escapeHtml(String(book.version || "unknown").slice(0, 12))}</div>
        <div class="book-info-status"><span class="book-info-dot"></span> 已通过完整性校验</div>
        <dl class="book-info-list">
          <div><dt>章节</dt><dd>${Number(book.chapter_count || files.length).toLocaleString()}</dd></div>
          <div><dt>Wiki 页面</dt><dd>${Number(book.page_count || 0).toLocaleString()}</dd></div>
          <div><dt>关系边</dt><dd>${Number(book.total_relations || 0).toLocaleString()}</dd></div>
          <div><dt>未解析</dt><dd>${Number(book.unresolved || 0).toLocaleString()} · ${(Number(book.unresolved_ratio || 0) * 100).toFixed(2)}%</dd></div>
        </dl>
        <div class="book-info-mode">${App.escapeHtml(book.reading_experience_mode || "rule_only")}</div>`;
    }

    function renderChapterInfo(chapter, data) {
      if (!chapter) return renderBookInfo();
      const sources = (chapter.sources || []).slice(0, 4);
      info.innerHTML = `<div class="book-info-eyebrow">CHAPTER ${String(chapter.order).padStart(3, "0")}</div>
        <div class="book-info-title">${App.escapeHtml(chapter.title || chapter.chapter_id)}</div>
        <div class="book-info-status"><span class="book-info-dot"></span> 当前阅读</div>
        <dl class="book-info-list">
          <div><dt>章节大小</dt><dd>${Math.ceil((data.size || chapter.size || 0) / 1024)} KB</dd></div>
          <div><dt>来源文件</dt><dd>${sources.length}${chapter.sources && chapter.sources.length > sources.length ? "+" : ""}</dd></div>
        </dl>
        <div class="book-info-section-title">来源</div>
        <ul class="book-info-sources">${sources.length ? sources.map(source => `<li>${App.escapeHtml(source)}</li>`).join("") : "<li>暂无来源记录</li>"}</ul>`;
    }

    loadStatus();
    loadVersions();
  };
})();

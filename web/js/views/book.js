// ruflo-kb — Book view: one-click build of the KC Book view, with the
// read-only Wiki reader kept as the fallback for projects that have no
// Knowledge Compiler data yet.
//
// Two surfaces share this page:
//   * Build panel  -> GET  /api/v1/kc/book/status
//                     POST /api/v1/kc/book/build   (dry-run by default)
//   * Reader pane  -> the existing read-only Wiki listing (unchanged)
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
          <input id="bookSearch" class="book-search" placeholder="搜索章节标题…" aria-label="搜索章节标题" />
        </div>
        <div class="book-layout">
          <aside class="book-toc" id="bookToc"><div class="skeleton skeleton-line"></div></aside>
          <article class="book-reader" id="bookReader">
            <div class="book-reader-empty"><span>✦</span><h2>选择一页开始阅读</h2><p>左侧目录会按 Wiki 类型整理当前实例。</p></div>
          </article>
        </div>
      </section>`;

    const toc = root.querySelector("#bookToc");
    const reader = root.querySelector("#bookReader");
    const stats = root.querySelector("#bookStats");
    const volumeBar = root.querySelector("#bookVolumes");
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

    // ---------- Read-only Wiki reader (fallback surface) ----------

    App.api(`/api/v1/projects/${App.state.projectId}/files?root=wiki&recursive=true&max_files=10000`)
      .then(data => {
        files = (data.files || []).filter(file => !file.isDir && file.path.endsWith(".md"));
        stats.textContent = `${files.length.toLocaleString()} 页 Wiki`;
        renderToc();
      })
      .catch(error => {
        stats.textContent = "加载失败";
        toc.innerHTML = `<div class="banner-err">Book 加载失败：${App.escapeHtml(error.message)}</div>`;
      });

    function volumeFor(path) {
      const parts = App.normalizeWikiPath(path).split("/");
      return ["sources", "concepts", "entities", "synthesis"].includes(parts[0]) ? parts[0] : "other";
    }

    function renderToc() {
      const filtered = files.filter(file => {
        const volume = volumeFor(file.path);
        const title = (file.path.split(/[\\/]/).pop() || "").replace(/\.md$/, "");
        return (selectedVolume === "all" || volume === selectedVolume) && (!query || title.toLowerCase().includes(query));
      });
      const grouped = new Map();
      for (const file of filtered) {
        const volume = volumeFor(file.path);
        if (!grouped.has(volume)) grouped.set(volume, []);
        grouped.get(volume).push(file);
      }
      const labels = { sources: "Sources · 来源", concepts: "Concepts · 概念", entities: "Entities · 实体", synthesis: "Synthesis · 综合", other: "Other" };
      if (!filtered.length) {
        toc.innerHTML = `<div class="book-empty">没有匹配的章节</div>`;
        return;
      }
      toc.innerHTML = Array.from(grouped, ([volume, items]) => `
        <section class="book-volume-group">
          <div class="book-volume-heading">${labels[volume]} <span>${items.length}</span></div>
          ${items.slice(0, 300).map(file => {
            const title = (file.path.split(/[\\/]/).pop() || "").replace(/\.md$/, "");
            return `<button class="book-chapter" data-path="${App.escapeHtml(App.normalizeWikiPath(file.path))}">${App.escapeHtml(title)}</button>`;
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
        const data = await App.api(`/api/v1/projects/${App.state.projectId}/files/content?path=${encodeURIComponent(button.dataset.path)}`);
        const parsed = App.parseFrontmatter(data.content || "");
        const title = button.textContent;
        reader.innerHTML = `<div class="book-reader-kicker">${App.escapeHtml(volumeFor(button.dataset.path))}</div>
          <h2>${App.escapeHtml(title)}</h2>${App.renderFrontmatter(parsed.fm)}<div class="reader-body">${App.renderMd(parsed.body)}</div>`;
        App.updateBreadcrumb(`book/${button.dataset.path}`);
      } catch (error) {
        reader.innerHTML = `<div class="banner-err">章节读取失败：${App.escapeHtml(error.message)}</div>`;
      }
    }

    loadStatus();
  };
})();

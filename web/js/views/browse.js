// ruflo-kb — browse view (wiki tree + tag filter + TOC + backlinks §1.3).
(() => {
  "use strict";

  window.App = window.App || {};

  // Tag filter state
  App._selectedTags = [];
  App._tagIndex = null;

  App.renderBrowse = function renderBrowse(root) {
    root.innerHTML = `
      <div class="tag-filter" id="tagFilter">
        <div class="tag-filter-header">
          <span class="tag-filter-title">标签筛选</span>
          <span class="tag-filter-count" id="tagFilterCount"></span>
          <div class="tag-filter-selected" id="tagFilterSelected"></div>
        </div>
        <div class="tag-filter-rows" id="tagFilterRows">加载中...</div>
      </div>
      <div class="browse-grid">
        <div class="browse-tree" id="tree"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div></div>
        <div class="browse-reader" id="reader">
          <div id="readerToc" class="reader-toc"></div>
          <div id="readerBody" style="color:var(--text-secondary);">从左侧选择一个文件。</div>
          <div id="readerBacklinks" class="reader-backlinks"></div>
        </div>
      </div>
    `;

    // Load tag index and files in parallel
    Promise.all([
      App.api(`/api/v1/projects/${App.state.projectId}/tag-index`).catch(() => ({ namespaces: {} })),
      App.api(`/api/v1/projects/${App.state.projectId}/files?root=wiki&recursive=true&max_files=2000&include_tags=true`).catch(() => ({ files: [] })),
    ]).then(([tagIdx, filesData]) => {
      App._tagIndex = tagIdx;
      const allFiles = (filesData.files || []).filter(f => !f.isDir && f.path.endsWith(".md"));
      App._allWikiFiles = allFiles;
      renderTagFilter(tagIdx);
      renderTree(allFiles);
    });

    function renderTagFilter(tagIdx) {
      const rows = document.getElementById("tagFilterRows");
      const ns = tagIdx.namespaces || {};
      const prefixes = Object.keys(ns);
      if (!prefixes.length) {
        rows.innerHTML = "";
        document.getElementById("tagFilter").style.display = "none";
        return;
      }

      const DEFAULT_VISIBLE = 4;
      const expandedAll = prefixes.length <= DEFAULT_VISIBLE;
      let html = "";
      prefixes.forEach((prefix, idx) => {
        const nsData = ns[prefix];
        const hidden = !expandedAll && idx >= DEFAULT_VISIBLE;
        html += `<div class="tag-ns-row${hidden ? " tag-ns-hidden" : ""}" data-ns="${App.escapeHtml(prefix)}">
          <span class="tag-ns-label">${App.escapeHtml(nsData.label)}</span>
          <div class="tag-ns-chips">
            ${nsData.tags.map(t => {
              const selected = App._selectedTags.includes(prefix + "/" + t.name);
              return `<span class="tag-chip${selected ? " active" : ""}" data-tag="${App.escapeHtml(prefix + "/" + t.name)}">
                ${App.escapeHtml(t.name)}<span class="tag-chip-count">${t.count}</span>
              </span>`;
            }).join("")}
          </div>
        </div>`;
      });
      if (!expandedAll) {
        html += `<button class="tag-expand-btn" id="tagExpandBtn">展开更多 ▼</button>`;
      }
      rows.innerHTML = html;

      // Bind expand button
      const expandBtn = document.getElementById("tagExpandBtn");
      if (expandBtn) {
        expandBtn.addEventListener("click", () => {
          document.querySelectorAll(".tag-ns-hidden").forEach(el => el.classList.remove("tag-ns-hidden"));
          expandBtn.remove();
        });
      }

      // Bind chip clicks
      rows.querySelectorAll(".tag-chip").forEach(chip => {
        chip.addEventListener("click", () => {
          const tag = chip.dataset.tag;
          if (App._selectedTags.includes(tag)) {
            App._selectedTags = App._selectedTags.filter(t => t !== tag);
          } else {
            App._selectedTags.push(tag);
          }
          updateSelectedBar();
          rows.querySelectorAll(".tag-chip").forEach(c => {
            c.classList.toggle("active", App._selectedTags.includes(c.dataset.tag));
          });
          renderTree(App._allWikiFiles || []);
        });
      });

      updateSelectedBar();
    }

    function updateSelectedBar() {
      const bar = document.getElementById("tagFilterSelected");
      const count = document.getElementById("tagFilterCount");
      if (!bar) return;
      if (!App._selectedTags.length) {
        bar.innerHTML = "";
        if (count) count.textContent = "";
        return;
      }
      if (count) count.textContent = `(${App._allWikiFiles ? filterFiles(App._allWikiFiles).length : 0})`;
      bar.innerHTML = App._selectedTags.map(t => {
        const parts = t.split("/");
        return `<span class="tag-remove-chip" data-tag="${App.escapeHtml(t)}">
          ${App.escapeHtml(parts[1] || t)} ×
        </span>`;
      }).join("");
      bar.querySelectorAll(".tag-remove-chip").forEach(chip => {
        chip.addEventListener("click", () => {
          App._selectedTags = App._selectedTags.filter(t => t !== chip.dataset.tag);
          updateSelectedBar();
          document.querySelectorAll("#tagFilterRows .tag-chip").forEach(c => {
            c.classList.toggle("active", App._selectedTags.includes(c.dataset.tag));
          });
          renderTree(App._allWikiFiles || []);
        });
      });
    }

    function filterFiles(files) {
      if (!App._selectedTags.length) return files;
      const selectedByNs = {};
      for (const t of App._selectedTags) {
        const idx = t.indexOf("/");
        const ns = idx >= 0 ? t.slice(0, idx) : t;
        if (!selectedByNs[ns]) selectedByNs[ns] = new Set();
        selectedByNs[ns].add(t);
      }
      return files.filter(f => {
        const tags = f.tags || [];
        for (const ns of Object.keys(selectedByNs)) {
          const nsTags = selectedByNs[ns];
          const hasAny = tags.some(t => nsTags.has(t));
          if (!hasAny) return false;
        }
        return true;
      });
    }

    function renderTree(files) {
      const tree = document.getElementById("tree");
      const filtered = filterFiles(files);

      // Update tag filter count
      const count = document.getElementById("tagFilterCount");
      if (count) count.textContent = App._selectedTags.length ? `(${filtered.length})` : "";

      if (!filtered.length) {
        tree.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">📂</div>
          <div class="empty-state-title">没有匹配的文件</div>
          <div class="empty-state-desc">尝试调整或清除标签筛选条件</div>
        </div>`;
        return;
      }

      const groups = new Map();
      for (const f of filtered) {
        const rel = App.normalizeWikiPath(f.path || "");
        if (!rel.endsWith(".md")) continue;
        const parts = rel.split("/");
        const groupKey = parts.length === 1 ? "系统" : parts[0];
        if (!groups.has(groupKey)) groups.set(groupKey, []);
        groups.get(groupKey).push({ path: rel, name: parts[parts.length - 1] });
      }
      const sortedKeys = Array.from(groups.keys()).sort((a, b) => {
        if (a === "系统") return -1; if (b === "系统") return 1;
        return a.localeCompare(b);
      });
      tree.innerHTML = sortedKeys.map(gk => {
        const count = groups.get(gk).length;
        return `
          <div class="tree-group">
            <div class="tree-group-title">${App.escapeHtml(gk)} <span class="tree-group-count">(${count})</span></div>
            <div class="tree-files">
              ${groups.get(gk).sort((a, b) => a.name.localeCompare(b.name)).map(f => {
                const disp = f.name.replace(/\.md$/, "");
                return `<div class="tree-file" data-path="${App.escapeHtml(f.path)}">${App.escapeHtml(disp)}</div>`;
              }).join("")}
            </div>
          </div>
        `;
      }).join("");
      tree.querySelectorAll(".tree-group-title").forEach(t => {
        t.addEventListener("click", () => t.parentElement.classList.toggle("collapsed"));
      });
      tree.querySelectorAll(".tree-file").forEach(el => {
        el.addEventListener("click", () => {
          tree.querySelectorAll(".tree-file").forEach(x => x.classList.remove("active"));
          el.classList.add("active");
          loadReader(el.dataset.path);
        });
      });
      const target = App.state.pendingBrowseTarget;
      if (target) {
        App.state.pendingBrowseTarget = null;
        const node = tree.querySelector(`.tree-file[data-path="${CSS.escape(target)}"]`);
        if (node) {
          let p = node.parentElement;
          while (p && !p.classList.contains("tree-group")) p = p.parentElement;
          if (p) p.classList.remove("collapsed");
          node.click();
        }
      }
    }

    async function loadReader(path) {
      const readerBody = document.getElementById("readerBody");
      const tocEl = document.getElementById("readerToc");
      const backlinksEl = document.getElementById("readerBacklinks");
      readerBody.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div>`;
      tocEl.innerHTML = "";
      backlinksEl.innerHTML = "";
      try {
        const stripped = App.normalizeWikiPath(path);
        const fc = await App.api(`/api/v1/projects/${App.state.projectId}/files/content?path=${encodeURIComponent(stripped)}`);
        const { fm, body } = App.parseFrontmatter(fc.content || "");
        readerBody.innerHTML = App.renderFrontmatter(fm) + `<div class="reader-body">${App.renderMd(body)}</div>`;

        // TOC: extract ## and ### headings
        const headings = body.match(/^#{2,3}\s+.+$/gm);
        if (headings && headings.length) {
          const tocItems = headings.map((h, idx) => {
            const level = h.startsWith("###") ? 3 : 2;
            const text = h.replace(/^#{2,3}\s+/, "");
            return `<a class="toc-item toc-level-${level}" data-heading="${idx}">${App.escapeHtml(text)}</a>`;
          }).join("");
          tocEl.innerHTML = `<div class="toc-title">目录</div>${tocItems}`;
        }

        // Backlinks from frontmatter relations
        if (fm && fm.relations && Array.isArray(fm.relations) && fm.relations.length) {
          const items = fm.relations.map(r => {
            const target = typeof r === "string" ? r : (r.target || r.title || "");
            const label = typeof r === "string" ? r : (r.title || r.target || "");
            const rtype = typeof r === "object" ? (r.type || "") : "";
            return `<div class="backlink-item" data-target="${App.escapeHtml(target)}">
              <span class="backlink-label">${App.escapeHtml(label)}</span>
              ${rtype ? `<span class="backlink-type">${App.escapeHtml(rtype)}</span>` : ""}
            </div>`;
          }).join("");
          backlinksEl.innerHTML = `<div class="backlinks-title">相关笔记</div>${items}`;
          backlinksEl.querySelectorAll(".backlink-item").forEach(item => {
            item.addEventListener("click", () => {
              App.state.pendingBrowseTarget = item.dataset.target;
              App.showView("browse");
            });
          });
        }

        App.updateBreadcrumb(path);
      } catch (e) {
        readerBody.innerHTML = `<div class="banner-err">读取失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }
  };

  // Keep ingestOneRaw and formatSize for backward compat (also used by ingest view).
  App.ingestOneRaw = async function ingestOneRaw(path, onDone, onError, onProgress) {
    try {
      const r = await App.api(`/api/v1/projects/${App.state.projectId}/ingest`, {
        method: "POST",
        body: { source: path, folderContext: null },
      });
      if (r.status === "ignored") { onDone(); return; }
      if (r.status !== "queued" || !r.taskId) { onError("未识别状态"); return; }
      const POLL_MS = 1500;
      for (let i = 0; i < 600; i++) {
        await new Promise(res => setTimeout(res, POLL_MS));
        let rec;
        try { rec = await App.api(`/api/v1/projects/${App.state.projectId}/ingest/status/${encodeURIComponent(r.taskId)}`); }
        catch { break; }
        if (onProgress) { onProgress(rec); }
        if (rec.status === "succeeded") { onDone(); return; }
        if (rec.status === "failed") { onError(rec.error || "failed"); return; }
        if (i === 239 && rec.status === "running") { i--; continue; }
      }
      onError("超时");
    } catch (e) {
      onError(e.message);
    }
  };

  App.formatSize = function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };
})();

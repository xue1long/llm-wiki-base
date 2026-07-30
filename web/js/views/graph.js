// ruflo-kb — wiki graph view (force-directed SVG).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderGraph = function renderGraph(root) {
    root.innerHTML = `
      <div class="graph-toolbar">
        <span id="graphStats">加载中...</span>
        <span class="graph-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#2563eb"></span>concept</span>
          <span class="legend-item"><span class="legend-dot" style="background:#16a34a"></span>entity</span>
          <span class="legend-item"><span class="legend-dot" style="background:#d97706"></span>source</span>
          <span class="legend-item"><span class="legend-dot" style="background:#6b7280"></span>other</span>
        </span>
      </div>
      <div class="graph-canvas-wrap" id="graphCanvasWrap">
        <svg id="graphSvg" class="graph-canvas"></svg>
        <div class="graph-tooltip" id="graphTooltip" style="display:none;"></div>
        <div class="graph-zoom-controls">
          <button id="zoomInBtn" title="放大">+</button>
          <button id="zoomOutBtn" title="缩小">−</button>
          <button id="zoomResetBtn" title="重置">↺</button>
        </div>
      </div>
    `;
    const svg = root.querySelector("#graphSvg");
    const tooltip = root.querySelector("#graphTooltip");
    const wrap = root.querySelector("#graphCanvasWrap");

    let currentZoom = 1;
    function updateZoom(delta) {
      currentZoom = Math.max(0.2, Math.min(3, currentZoom + delta));
      const w = svg.clientWidth || 800;
      const h = svg.clientHeight || 600;
      svg.setAttribute("viewBox", `${0} ${0} ${w / currentZoom} ${h / currentZoom}`);
    }
    root.querySelector("#zoomInBtn").addEventListener("click", () => updateZoom(0.2));
    root.querySelector("#zoomOutBtn").addEventListener("click", () => updateZoom(-0.2));
    root.querySelector("#zoomResetBtn").addEventListener("click", () => { currentZoom = 1; updateZoom(0); });

    App.api(`/api/v1/projects/${App.state.projectId}/wiki/graph`)
      .then(g => {
        root.querySelector("#graphStats").textContent =
          `${g.counts.nodes} 节点 / ${g.counts.edges} 关系`;
        App.drawGraph(svg, g, tooltip);
      })
      .catch(e => {
        root.querySelector("#graphStats").textContent = "加载失败: " + e.message;
      });
  };

  App.drawGraph = function drawGraph(svg, g, tooltip) {
    const width = svg.clientWidth || 800;
    const height = svg.clientHeight || 600;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = "";

    const cx = width / 2, cy = height / 2;
    const R = Math.min(width, height) * 0.35;
    const nodes = g.nodes.map((n, i) => ({
      ...n,
      x: cx + R * Math.cos(2 * Math.PI * i / g.nodes.length),
      y: cy + R * Math.sin(2 * Math.PI * i / g.nodes.length),
      vx: 0, vy: 0,
    }));
    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const edges = g.edges.filter(e => nodeById.has(e.source) && nodeById.has(e.target));

    const TYPE_COLOR = {
      concept: "#2563eb",
      entity:  "#16a34a",
      source:  "#d97706",
      synthesis: "#9333ea",
    };
    function color(n) { return TYPE_COLOR[n.type] || "#6b7280"; }

    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
        markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af" />
    </marker>`;
    svg.appendChild(defs);

    const edgesG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(edgesG);
    const nodesG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(nodesG);

    function renderEdges() {
      edgesG.innerHTML = "";
      for (const e of edges) {
        const s = nodeById.get(e.source), t = nodeById.get(e.target);
        const ln = document.createElementNS("http://www.w3.org/2000/svg", "line");
        ln.setAttribute("x1", s.x); ln.setAttribute("y1", s.y);
        ln.setAttribute("x2", t.x); ln.setAttribute("y2", t.y);
        ln.setAttribute("stroke", "#9ca3af");
        ln.setAttribute("stroke-width", String(Math.min(2.5, Math.max(0.5, e.weight || 1))));
        ln.setAttribute("opacity", "0.45");
        ln.setAttribute("marker-end", "url(#arrow)");
        edgesG.appendChild(ln);
      }
    }

    function renderNodes() {
      nodesG.innerHTML = "";
      for (const n of nodes) {
        const g_el = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g_el.setAttribute("transform", `translate(${n.x},${n.y})`);
        g_el.style.cursor = "pointer";
        const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("r", "8");
        c.setAttribute("fill", color(n));
        c.setAttribute("stroke", "#ffffff"); c.setAttribute("stroke-width", "1.5");
        const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
        t.textContent = n.title + (n.type ? ` (${n.type})` : "");
        g_el.appendChild(c); g_el.appendChild(t);
        const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
        txt.setAttribute("x", 11); txt.setAttribute("y", 4);
        txt.setAttribute("font-size", "10"); txt.setAttribute("fill", "#1f2329");
        txt.textContent = (n.title || n.id).slice(0, 22);
        g_el.appendChild(txt);
        g_el.addEventListener("click", () => {
          App.state.pendingBrowseTarget = n.path;
          App.showView("browse");
        });
        // Hover tooltip
        g_el.addEventListener("mouseenter", (ev) => {
          if (!tooltip) return;
          const edgeCount = edges.filter(e => e.source === n.id || e.target === n.id).length;
          tooltip.innerHTML = `<strong>${App.escapeHtml(n.title || n.id)}</strong>
            <div style="font-size:11px;color:var(--text-muted);">${App.escapeHtml(n.type || "unknown")} · ${edgeCount} 条关联</div>`;
          tooltip.style.display = "block";
        });
        g_el.addEventListener("mousemove", (ev) => {
          if (!tooltip) return;
          const rect = svg.getBoundingClientRect();
          tooltip.style.left = (ev.clientX - rect.left + 14) + "px";
          tooltip.style.top = (ev.clientY - rect.top - 10) + "px";
        });
        g_el.addEventListener("mouseleave", () => {
          if (tooltip) tooltip.style.display = "none";
        });
        nodesG.appendChild(g_el);
      }
    }

    const iterations = 120;
    const area = width * height;
    const k = Math.sqrt(area / Math.max(1, nodes.length)) * 0.6;
    let temperature = Math.min(width, height) * 0.1;

    function step() {
      for (let i = 0; i < nodes.length; i++) {
        nodes[i].vx = 0; nodes[i].vy = 0;
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue;
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const rep = (k * k) / dist;
          nodes[i].vx += (dx / dist) * rep;
          nodes[i].vy += (dy / dist) * rep;
        }
      }
      for (const e of edges) {
        const s = nodeById.get(e.source), t = nodeById.get(e.target);
        const dx = s.x - t.x, dy = s.y - t.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const attr = (dist * dist) / k;
        const ux = dx / dist, uy = dy / dist;
        s.vx -= ux * attr; s.vy -= uy * attr;
        t.vx += ux * attr; t.vy += uy * attr;
      }
      let mx = 0, my = 0;
      for (const n of nodes) {
        const disp = Math.sqrt(n.vx * n.vx + n.vy * n.vy) || 0.01;
        const capped = Math.min(disp, temperature) / disp;
        n.x += n.vx * capped; n.y += n.vy * capped;
        n.x = Math.max(20, Math.min(width - 20, n.x));
        n.y = Math.max(20, Math.min(height - 20, n.y));
        mx += n.x; my += n.y;
      }
      mx /= nodes.length; my /= nodes.length;
      const dxC = cx - mx, dyC = cy - my;
      if (Math.abs(dxC) > 1 || Math.abs(dyC) > 1) {
        for (const n of nodes) { n.x += dxC; n.y += dyC; }
      }
      temperature *= 0.97;
    }

    let frame = 0;
    function animate() {
      if (frame++ >= iterations) {
        renderEdges(); renderNodes();
        return;
      }
      step();
      if (frame % 4 === 0) {
        renderEdges(); renderNodes();
      }
      requestAnimationFrame(animate);
    }
    renderEdges(); renderNodes();
    requestAnimationFrame(animate);
  };
})();

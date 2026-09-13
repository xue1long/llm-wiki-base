// ruflo-kb — settings modal (model providers + search controls).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderModelSettings = function renderModelSettings(root) {
    const PROVIDER_PRESETS = {
      "minimax": { base_url: "https://api.minimax.chat/v1", model: "MiniMax-Text-01", label: "MiniMax" },
      "kimi": { base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k", label: "Kimi / Moonshot" },
      "deepseek": { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", label: "DeepSeek" },
      "glm": { base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-plus", label: "GLM / 智谱" },
      "openai": { base_url: "https://api.openai.com/v1", model: "gpt-4o", label: "OpenAI（官方）" },
      "anthropic": { base_url: "", model: "", label: "Anthropic" },
      "ollama": { base_url: "http://127.0.0.1:11434", model: "", label: "Ollama（本地）" },
    };

    root.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <h2 style="margin:0;">LLM 提供商设置</h2>
        <button class="btn-primary" id="openAddModalBtn">+ 添加</button>
      </div>
      <div class="provider-grid" id="providerGrid">
        <div class="provider-card"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div></div>
      </div>
      <div id="providerConfigWarning" class="banner-warn" style="display:none;margin-top:12px;"></div>
      <div class="settings-section" style="margin-top:24px;">
        <h3 style="font-size:14px;margin:0 0 8px;">测试连接</h3>
        <div style="display:flex;gap:8px;align-items:center;">
          <select id="testProvName" style="padding:5px 8px;border:1px solid var(--border-hover);border-radius:var(--radius-md);font-size:13px;background:var(--bg-surface);">
            <option value="">选择提供商...</option>
          </select>
          <button class="btn-sm" id="testProvBtn">测试</button>
          <span id="testProvResult" style="margin-left:8px;font-size:13px;"></span>
        </div>
      </div>
    `;

    document.getElementById("openAddModalBtn").addEventListener("click", () => showAddModal());
    loadSettings();

    async function loadSettings() {
      const grid = document.getElementById("providerGrid");
      try {
        const data = await App.api("/api/v1/providers");
        renderProviderCards(data.providers || [], data.default_error || "");
      } catch (e) {
        grid.innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    function renderProviderCards(providers, defaultError) {
      const grid = document.getElementById("providerGrid");
      const testSelect = document.getElementById("testProvName");
      const warning = document.getElementById("providerConfigWarning");
      if (defaultError) {
        warning.style.display = "block";
        warning.textContent = "默认提供商解析失败：" + defaultError + "。请先修正配置，再删除提供商。";
      } else {
        warning.style.display = "none";
        warning.textContent = "";
      }

      if (!providers.length) {
        grid.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">⚙️</div>
          <div class="empty-state-title">暂无提供商</div>
          <div class="empty-state-desc">点击"+ 添加"配置 LLM 提供商</div>
        </div>`;
        testSelect.innerHTML = '<option value="">选择提供商...</option>';
        return;
      }

      testSelect.innerHTML = '<option value="">选择提供商...</option>' +
        providers.map(p => `<option value="${App.escapeHtml(p.name)}">${App.escapeHtml(p.name)}</option>`).join("");

      const typeLabels = { openai: "OpenAI", "openai-compatible": "OpenAI 兼容", anthropic: "Anthropic", ollama: "Ollama" };

      grid.innerHTML = providers.map(p => {
        const typeLabel = typeLabels[p.type] || p.type;
        const starIcon = p.is_default ? "★" : "☆";
        const starTitle = p.is_default ? "当前默认" : "设为默认";
        const starClass = p.is_default ? "star-active" : "";
        const chatModel = p.default_chat_model || "—";
        const embeddingModel = p.default_embedding_model || "—";
        const baseUrl = p.base_url || "—";
        const keyDisplay = p.api_key || "—";

        return `<div class="provider-card${p.is_default ? " default" : ""}">
          <div class="provider-card-header">
            <div class="provider-card-title">
              <span class="provider-card-name">${App.escapeHtml(p.name)}</span>
              <span class="provider-card-type">${App.escapeHtml(typeLabel)}</span>
            </div>
            <button class="star-btn ${starClass}" data-action="toggle-default" data-name="${App.escapeHtml(p.name)}" title="${starTitle}">${starIcon}</button>
          </div>
          <div class="provider-card-body">
            <div class="provider-card-field">
              <span class="provider-card-label">Chat Model</span>
              <span class="provider-card-value">${App.escapeHtml(chatModel)}</span>
            </div>
            <div class="provider-card-field">
              <span class="provider-card-label">Embedding Model</span>
              <span class="provider-card-value">${App.escapeHtml(embeddingModel)}</span>
            </div>
            <div class="provider-card-field">
              <span class="provider-card-label">Base URL</span>
              <span class="provider-card-value" style="font-size:11px;">${App.escapeHtml(baseUrl)}</span>
            </div>
            <div class="provider-card-field">
              <span class="provider-card-label">API Key</span>
              <span class="provider-card-value">${App.escapeHtml(keyDisplay)}</span>
            </div>
          </div>
          <div class="provider-card-test" id="testBanner-${App.escapeHtml(p.name)}" style="display:none;"></div>
          <div class="provider-card-actions">
            <button class="btn-sm" data-action="test" data-name="${App.escapeHtml(p.name)}">测试</button>
            <button class="btn-sm" data-action="edit" data-name="${App.escapeHtml(p.name)}">编辑</button>
            <button class="btn-sm btn-danger" data-action="remove" data-name="${App.escapeHtml(p.name)}">删除</button>
          </div>
        </div>`;
      }).join("");

      // Star toggle
      grid.querySelectorAll('[data-action="toggle-default"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          try {
            await App.api("/api/v1/providers/set-default", { method: "POST", body: { name } });
            loadSettings();
          } catch (e) {
            App.toast("设置默认失败: " + e.message, "error");
          }
        });
      });

      // Test button in card
      grid.querySelectorAll('[data-action="test"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          const banner = document.getElementById("testBanner-" + App.escapeHtml(name));
          if (!banner) return;
          banner.style.display = "block";
          banner.innerHTML = '<span style="color:var(--text-muted);">测试中...</span>';
          banner.className = "provider-card-test testing";
          try {
            const r = await App.api("/api/v1/providers/test?name=" + encodeURIComponent(name), { method: "POST" });
            if (r.ok) {
              banner.innerHTML = '<span>✓ ' + App.escapeHtml(r.detail || "连接正常") + '</span>';
              banner.className = "provider-card-test success";
            } else {
              banner.innerHTML = '<span>✗ ' + App.escapeHtml(r.error || "连接失败") + '</span>';
              banner.className = "provider-card-test error";
            }
          } catch (e) {
            banner.innerHTML = '<span>✗ ' + App.escapeHtml(e.message) + '</span>';
            banner.className = "provider-card-test error";
          }
        });
      });

      // Edit button
      grid.querySelectorAll('[data-action="edit"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          try {
            const r = await App.api("/api/v1/providers/" + encodeURIComponent(name));
            if (!r.ok && r.provider === undefined) throw new Error(r.error || "加载失败");
            showEditModal(r.provider);
          } catch (e) {
            App.toast("加载提供商失败: " + e.message, "error");
          }
        });
      });

      // Delete button
      grid.querySelectorAll('[data-action="remove"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          if (!confirm("确认删除提供商「" + name + "」？")) return;
          try {
            await App.api("/api/v1/providers/" + encodeURIComponent(name), { method: "DELETE" });
            loadSettings();
          } catch (e) {
            App.toast("删除失败: " + e.message, "error");
          }
        });
      });

      // Wire up test select
      document.getElementById("testProvBtn").addEventListener("click", async () => {
        const name = document.getElementById("testProvName").value;
        const result = document.getElementById("testProvResult");
        if (!name) { result.textContent = "请选择提供商"; result.style.color = ""; return; }
        result.textContent = "测试中...";
        result.style.color = "";
        try {
          const r = await App.api("/api/v1/providers/test?name=" + encodeURIComponent(name), { method: "POST" });
          result.textContent = r.ok ? "✓ " + (r.detail || "正常") : "✗ " + (r.error || "失败");
          result.style.color = r.ok ? "var(--success)" : "var(--danger)";
        } catch (e) {
          result.textContent = "✗ " + e.message;
          result.style.color = "var(--danger)";
        }
      });
    }

    function showEditModal(provider) {
      const existing = document.getElementById("addProviderModal");
      if (existing) existing.remove();

      const modal = document.createElement("div");
      modal.id = "addProviderModal";
      modal.className = "modal-overlay";
      modal.innerHTML = `<div class="modal-card">
        <div class="modal-header">
          <h3>编辑提供商</h3>
          <button class="modal-close" id="closeAddModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="modal-field">
            <label>名称</label>
            <input id="modalProvName" value="${App.escapeHtml(provider.name)}" readonly />
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">名称不可修改；如需新名称请添加新的提供商</div>
          </div>
          <div class="modal-field">
            <label>预设</label>
            <select id="modalProvPreset">
              <option value="">（自定义）</option>
              ${Object.entries(PROVIDER_PRESETS).map(([k, v]) =>
                `<option value="${k}">${v.label}</option>`
              ).join("")}
            </select>
          </div>
          <div class="modal-field">
            <label>类型</label>
            <select id="modalProvType">
              <option value="openai-compatible"${provider.type === "openai-compatible" ? " selected" : ""}>OpenAI 兼容</option>
              <option value="openai"${provider.type === "openai" ? " selected" : ""}>OpenAI（官方）</option>
              <option value="anthropic"${provider.type === "anthropic" ? " selected" : ""}>Anthropic</option>
              <option value="ollama"${provider.type === "ollama" ? " selected" : ""}>Ollama</option>
            </select>
          </div>
          <div class="modal-field">
            <label>Base URL</label>
            <input id="modalProvBaseUrl" value="${App.escapeHtml(provider.base_url || "")}" />
          </div>
          <div class="modal-field">
            <label>API Key</label>
            <input id="modalProvKey" type="password" placeholder="留空不修改" value="${provider.api_key ? "***" : ""}" />
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">留空保持原有值不变</div>
          </div>
          <div class="modal-field">
            <label>默认 Chat 模型</label>
            <input id="modalProvChatModel" value="${App.escapeHtml(provider.default_chat_model || "")}" />
          </div>
          <div class="modal-field">
            <label>默认 Embedding 模型</label>
            <input id="modalProvEmbeddingModel" value="${App.escapeHtml(provider.default_embedding_model || "")}" />
          </div>
          <div id="modalAddResult" style="margin-top:8px;"></div>
        </div>
        <div class="modal-footer">
          <button class="btn-sm" id="cancelAddModal">取消</button>
          <button class="btn-primary" id="confirmAddModal">保存</button>
        </div>
      </div>`;
      document.body.appendChild(modal);

      // Preset auto-fill
      modal.querySelector("#modalProvPreset").addEventListener("change", () => {
        const preset = PROVIDER_PRESETS[modal.querySelector("#modalProvPreset").value];
        if (!preset) return;
        const nameEl = document.getElementById("modalProvName");
        if (!nameEl.value.trim() || nameEl.value === provider.name) nameEl.value = modal.querySelector("#modalProvPreset").value;
        document.getElementById("modalProvBaseUrl").value = preset.base_url || "";
        document.getElementById("modalProvChatModel").value = preset.model || "";
        if (preset.label.includes("Anthropic")) {
          document.getElementById("modalProvType").value = "anthropic";
        } else if (preset.label.includes("Ollama")) {
          document.getElementById("modalProvType").value = "ollama";
        } else if (preset.label === "OpenAI（官方）") {
          document.getElementById("modalProvType").value = "openai";
        } else {
          document.getElementById("modalProvType").value = "openai-compatible";
        }
      });

      function closeModal() { modal.remove(); }
      modal.querySelector("#closeAddModal").addEventListener("click", closeModal);
      modal.querySelector("#cancelAddModal").addEventListener("click", closeModal);
      modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

      modal.querySelector("#confirmAddModal").addEventListener("click", async () => {
        const name = document.getElementById("modalProvName").value.trim();
        const type = document.getElementById("modalProvType").value;
        const api_key = document.getElementById("modalProvKey").value;
        const base_url = document.getElementById("modalProvBaseUrl").value.trim();
        const chat_model = document.getElementById("modalProvChatModel").value.trim();
        const embedding_model = document.getElementById("modalProvEmbeddingModel").value.trim();
        const result = document.getElementById("modalAddResult");
        if (!name) { result.innerHTML = '<span class="banner-warn">请输入名称</span>'; return; }
        result.innerHTML = "保存中...";
        try {
          // POST /providers 是 upsert 语义，直接覆盖
          const body = { name, type, base_url, chat_model, embedding_model };
          // 只有用户手动输入了新 key 才传，否则后端保持原有值
          if (api_key && api_key !== "***") body.api_key = api_key;
          await App.api("/api/v1/providers", {
            method: "POST",
            body: body,
          });
          closeModal();
          loadSettings();
          App.toast("提供商「" + name + "」已更新", "success");
        } catch (e) {
          result.innerHTML = '<span class="banner-err">失败: ' + App.escapeHtml(e.message) + '</span>';
        }
      });
    }

    function showAddModal() {
      const existing = document.getElementById("addProviderModal");
      if (existing) existing.remove();

      const modal = document.createElement("div");
      modal.id = "addProviderModal";
      modal.className = "modal-overlay";
      modal.innerHTML = `<div class="modal-card">
        <div class="modal-header">
          <h3>添加提供商</h3>
          <button class="modal-close" id="closeAddModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="modal-field">
            <label>名称</label>
            <input id="modalProvName" placeholder="如 my-openai" />
          </div>
          <div class="modal-field">
            <label>预设</label>
            <select id="modalProvPreset">
              <option value="">（自定义）</option>
              ${Object.entries(PROVIDER_PRESETS).map(([k, v]) =>
                `<option value="${k}">${v.label}</option>`
              ).join("")}
            </select>
          </div>
          <div class="modal-field">
            <label>类型</label>
            <select id="modalProvType">
              <option value="openai-compatible">OpenAI 兼容</option>
              <option value="openai">OpenAI（官方）</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama</option>
            </select>
          </div>
          <div class="modal-field">
            <label>Base URL</label>
            <input id="modalProvBaseUrl" placeholder="https://api.example.com/v1" />
          </div>
          <div class="modal-field">
            <label>API Key</label>
            <input id="modalProvKey" type="password" placeholder="留空从环境变量读取" />
          </div>
          <div class="modal-field">
            <label>默认 Chat 模型</label>
            <input id="modalProvChatModel" placeholder="如 gpt-4o" />
          </div>
          <div class="modal-field">
            <label>默认 Embedding 模型</label>
            <input id="modalProvEmbeddingModel" placeholder="如 text-embedding-3-small" />
          </div>
          <div id="modalAddResult" style="margin-top:8px;"></div>
        </div>
        <div class="modal-footer">
          <button class="btn-sm" id="cancelAddModal">取消</button>
          <button class="btn-primary" id="confirmAddModal">添加</button>
        </div>
      </div>`;
      document.body.appendChild(modal);

      // Preset auto-fill
      modal.querySelector("#modalProvPreset").addEventListener("change", () => {
        const preset = PROVIDER_PRESETS[modal.querySelector("#modalProvPreset").value];
        if (!preset) return;
        const nameEl = document.getElementById("modalProvName");
        if (!nameEl.value.trim()) nameEl.value = modal.querySelector("#modalProvPreset").value;
        document.getElementById("modalProvBaseUrl").value = preset.base_url || "";
        document.getElementById("modalProvChatModel").value = preset.model || "";
        if (preset.label.includes("Anthropic")) {
          document.getElementById("modalProvType").value = "anthropic";
        } else if (preset.label.includes("Ollama")) {
          document.getElementById("modalProvType").value = "ollama";
        } else if (preset.label === "OpenAI（官方）") {
          document.getElementById("modalProvType").value = "openai";
        } else {
          document.getElementById("modalProvType").value = "openai-compatible";
        }
      });

      function closeModal() { modal.remove(); }
      modal.querySelector("#closeAddModal").addEventListener("click", closeModal);
      modal.querySelector("#cancelAddModal").addEventListener("click", closeModal);
      modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

      modal.querySelector("#confirmAddModal").addEventListener("click", async () => {
        const name = document.getElementById("modalProvName").value.trim();
        const type = document.getElementById("modalProvType").value;
        const api_key = document.getElementById("modalProvKey").value;
        const base_url = document.getElementById("modalProvBaseUrl").value.trim();
        const chat_model = document.getElementById("modalProvChatModel").value.trim();
        const embedding_model = document.getElementById("modalProvEmbeddingModel").value.trim();
        const result = document.getElementById("modalAddResult");
        if (!name) { result.innerHTML = '<span class="banner-warn">请输入名称</span>'; return; }
        result.innerHTML = "添加中...";
        try {
          await App.api("/api/v1/providers", {
            method: "POST",
            body: { name, type, api_key, base_url, chat_model, embedding_model },
          });
          closeModal();
          loadSettings();
          App.toast("提供商「" + name + "」已添加", "success");
        } catch (e) {
          result.innerHTML = '<span class="banner-err">失败: ' + App.escapeHtml(e.message) + '</span>';
        }
      });
    }
  };

  App.openSettingsModal = function openSettingsModal() {
    const existing = document.getElementById("settingsModal");
    if (existing) existing.remove();

    const opener = document.activeElement;
    const modal = document.createElement("div");
    modal.id = "settingsModal";
    modal.className = "settings-modal-overlay";
    modal.innerHTML = `
      <div class="settings-modal-card" role="dialog" aria-modal="true" aria-labelledby="settingsModalTitle">
        <div class="settings-modal-header">
          <div>
            <div class="settings-modal-kicker">ruflo-kb</div>
            <h2 id="settingsModalTitle">设置</h2>
          </div>
          <button class="modal-close" id="settingsModalClose" type="button" aria-label="关闭设置">&times;</button>
        </div>
        <div class="settings-modal-body">
          <nav class="settings-modal-nav" aria-label="设置分类">
            <button class="settings-nav-btn active" data-settings-page="model" type="button">模型</button>
            <button class="settings-nav-btn" data-settings-page="search" type="button">搜索</button>
            <button class="settings-nav-btn" data-settings-page="skills" type="button">Skills</button>
          </nav>
          <section class="settings-modal-panel" id="settingsModalPanel" aria-live="polite"></section>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    let panelCleanup = null;
    const panel = modal.querySelector("#settingsModalPanel");

    function close() {
      if (panelCleanup) panelCleanup();
      modal.remove();
      if (opener && typeof opener.focus === "function") opener.focus();
      document.removeEventListener("keydown", onKeyDown);
      App.closeSettingsModal = null;
    }

    function onKeyDown(e) {
      if (e.key === "Escape") close();
    }

    function renderPage(page) {
      if (panelCleanup) panelCleanup();
      panelCleanup = null;
      modal.querySelectorAll(".settings-nav-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.settingsPage === page);
      });
      if (page === "search") {
        panelCleanup = renderSearchSettings(panel);
      } else if (page === "skills") {
        panelCleanup = renderSkillSettings(panel);
      } else {
        App.renderModelSettings(panel);
      }
    }

    App.closeSettingsModal = close;
    modal.querySelector("#settingsModalClose").addEventListener("click", close);
    modal.addEventListener("click", e => { if (e.target === modal) close(); });
    modal.querySelectorAll(".settings-nav-btn").forEach(btn => {
      btn.addEventListener("click", () => renderPage(btn.dataset.settingsPage));
    });
    document.addEventListener("keydown", onKeyDown);
    renderPage("model");
    modal.querySelector(".settings-nav-btn").focus();
  };

  App.closeSettingsModal = null;

  function renderSkillSettings(root) {
    root.innerHTML = `
      <div class="settings-panel-heading">
        <div>
          <div class="settings-panel-eyebrow">SKILL LIBRARY</div>
          <h3>Agent Skills</h3>
          <p>把静态 Skill 导入独立 Library，再明确部署到 Agent。v1 不执行 Plugin、MCP、hook 或安装脚本。</p>
        </div>
      </div>
      <div class="skill-settings-flow">
        <section class="skill-settings-card">
          <div class="skill-settings-step">01 · SOURCE</div>
          <label class="skill-settings-label" for="skillSourcePath">本地 Skill 目录</label>
          <div class="skill-settings-input-row">
            <input id="skillSourcePath" type="text" placeholder="例如：E:\\skills\\my-skill" autocomplete="off" />
            <button class="btn-primary" id="skillInspectBtn" type="button">检查来源</button>
          </div>
          <div class="settings-help">目录根部必须包含 SKILL.md；出现 plugin.json 会明确拒绝。</div>
          <div id="skillInspectResult" class="skill-settings-result" aria-live="polite">等待检查来源...</div>
        </section>
        <section class="skill-settings-card">
          <div class="skill-settings-step">02 · LIBRARY</div>
          <div class="skill-settings-row">
            <div>
              <strong>已验证 Artifact</strong>
              <div class="settings-help">导入只写 Library，不会修改 Agent 目录。</div>
            </div>
            <button class="btn-sm" id="skillRefreshBtn" type="button">刷新</button>
          </div>
          <select id="skillArtifactSelect" class="skill-settings-select" aria-label="选择 Artifact">
            <option value="">暂无 Artifact</option>
          </select>
          <div id="skillImportResult" class="skill-settings-result" aria-live="polite"></div>
          <button class="btn-primary" id="skillImportBtn" type="button" disabled>确认导入 Artifact</button>
        </section>
        <section class="skill-settings-card">
          <div class="skill-settings-step">03 · DEPLOY</div>
          <div class="settings-help">先预览目标状态，再确认部署。冲突会停止整个计划，不覆盖已有内容。</div>
          <div id="skillAgents" class="skill-settings-agents">读取 Agent...</div>
          <button class="btn-sm" id="skillPlanBtn" type="button" disabled>生成部署计划</button>
          <div id="skillPlanResult" class="skill-settings-result" aria-live="polite"></div>
          <button class="btn-primary" id="skillDeployBtn" type="button" disabled>确认部署</button>
        </section>
      </div>
      <div class="skill-settings-card skill-settings-plugin-note">
        <span class="skill-settings-plugin-badge">PLUGIN · UNSUPPORTED</span>
        <span>Plugin 暂不支持安装。当前版本只处理不执行代码的静态 Skill。</span>
      </div>
    `;

    const sourceEl = root.querySelector("#skillSourcePath");
    const inspectBtn = root.querySelector("#skillInspectBtn");
    const inspectResult = root.querySelector("#skillInspectResult");
    const artifactSelect = root.querySelector("#skillArtifactSelect");
    const importBtn = root.querySelector("#skillImportBtn");
    const importResult = root.querySelector("#skillImportResult");
    const agentsEl = root.querySelector("#skillAgents");
    const planBtn = root.querySelector("#skillPlanBtn");
    const planResult = root.querySelector("#skillPlanResult");
    const deployBtn = root.querySelector("#skillDeployBtn");
    let inspection = null;
    let plan = null;
    let pollTimer = null;

    function setBusy(button, busy) {
      button.disabled = busy;
      if (busy) button.dataset.previousText = button.textContent;
      button.textContent = busy ? "处理中..." : (button.dataset.previousText || button.textContent);
    }

    function selectedAgents() {
      return [...root.querySelectorAll("input[name=skill-agent]:checked")].map(input => input.value);
    }

    function renderArtifacts(artifacts) {
      artifactSelect.innerHTML = artifacts.length
        ? artifacts.map(item => `<option value="${App.escapeHtml(item.artifact_id)}">${App.escapeHtml(item.name)} · ${App.escapeHtml(item.content_hash.slice(0, 12))}</option>`).join("")
        : '<option value="">暂无 Artifact</option>';
      const matching = inspection && artifacts.find(item => item.artifact_id === inspection.artifact_id);
      if (matching) artifactSelect.value = matching.artifact_id;
      updateActions();
    }

    function updateActions() {
      const hasArtifact = !!artifactSelect.value;
      importBtn.disabled = !inspection;
      planBtn.disabled = !hasArtifact || !selectedAgents().length;
      deployBtn.disabled = !plan || plan.targets.some(item => item.status === "conflict");
    }

    async function loadLibrary() {
      const data = await App.api("/api/v1/skill-manager/library");
      renderArtifacts(data.artifacts || []);
    }

    async function loadAgents() {
      const data = await App.api("/api/v1/skill-manager/agents");
      agentsEl.innerHTML = (data.agents || []).map(agent => `
        <label class="skill-settings-agent">
          <input type="checkbox" name="skill-agent" value="${App.escapeHtml(agent.id)}" ${agent.exists ? "" : "disabled"} />
          <span>${App.escapeHtml(agent.id)}</span>
          <small>${agent.exists ? "可用" : "目录不存在"}</small>
        </label>`).join("") || '<span class="settings-help">没有可用 Agent 目标</span>';
      root.querySelectorAll("input[name=skill-agent]").forEach(input => input.addEventListener("change", updateActions));
      updateActions();
    }

    inspectBtn.addEventListener("click", async () => {
      const source = sourceEl.value.trim();
      if (!source) { inspectResult.textContent = "请输入本地目录"; return; }
      setBusy(inspectBtn, true);
      try {
        inspection = await App.api("/api/v1/skill-manager/artifacts/inspect", { method: "POST", body: { source } });
        inspectResult.innerHTML = `<strong>${App.escapeHtml(inspection.name)}</strong> · ${inspection.file_count} 个文件 · ${inspection.total_bytes} bytes<br><code>${App.escapeHtml(inspection.content_hash)}</code>`;
        importResult.textContent = "检查通过；点击“确认导入 Artifact”写入 Library。";
        await loadLibrary();
      } catch (e) {
        inspection = null;
        inspectResult.textContent = e.message.includes("UNSUPPORTED_PLUGIN_TYPE") ? "Plugin 暂不支持" : "检查失败：" + e.message;
        updateActions();
      } finally { setBusy(inspectBtn, false); }
    });

    importBtn.addEventListener("click", async () => {
      if (!inspection || !window.confirm("确认把这个已检查的 Skill 导入 Library？不会写入 Agent。")) return;
      setBusy(importBtn, true);
      try {
        const result = await App.api("/api/v1/skill-manager/artifacts/import", { method: "POST", body: { source: sourceEl.value.trim(), plan_hash: inspection.content_hash, confirm: true } });
        importResult.textContent = "已导入 Artifact：" + result.artifact_id;
        await loadLibrary();
      } catch (e) { importResult.textContent = "导入失败：" + e.message; }
      finally { setBusy(importBtn, false); }
    });

    root.querySelector("#skillRefreshBtn").addEventListener("click", () => loadLibrary().catch(e => { importResult.textContent = "刷新失败：" + e.message; }));
    planBtn.addEventListener("click", async () => {
      setBusy(planBtn, true);
      try {
        plan = await App.api("/api/v1/skill-manager/deployments/plan", { method: "POST", body: { artifact_id: artifactSelect.value, target_ids: selectedAgents() } });
        planResult.innerHTML = plan.targets.map(item => `<div><span class="skill-status-${item.status}">${App.escapeHtml(item.status)}</span> ${App.escapeHtml(item.id)}${item.reason ? " · " + App.escapeHtml(item.reason) : ""}</div>`).join("");
      } catch (e) { plan = null; planResult.textContent = "计划失败：" + e.message; }
      finally { setBusy(planBtn, false); updateActions(); }
    });

    deployBtn.addEventListener("click", async () => {
      if (!plan || !window.confirm("确认部署到选中的 Agent？冲突目标不会被覆盖。")) return;
      setBusy(deployBtn, true);
      try {
        const result = await App.api("/api/v1/skill-manager/deployments/apply", { method: "POST", body: { artifact_id: plan.artifact_id, target_ids: selectedAgents(), plan_hash: plan.plan_hash, confirm: true } });
        planResult.textContent = "Operation " + result.operation_id + "：" + result.status;
        const operationId = result.operation_id;
        pollTimer = setInterval(async () => {
          try {
            const status = await App.api("/api/v1/skill-manager/operations/" + encodeURIComponent(operationId));
            planResult.textContent = "Operation " + operationId + "：" + status.status;
            if (["succeeded", "failed", "conflict", "partial_failure"].includes(status.status)) { clearInterval(pollTimer); pollTimer = null; setBusy(deployBtn, false); }
          } catch (e) { clearInterval(pollTimer); pollTimer = null; planResult.textContent = "状态读取失败：" + e.message; setBusy(deployBtn, false); }
        }, 1000);
      } catch (e) { planResult.textContent = "部署失败：" + e.message; setBusy(deployBtn, false); }
    });

    Promise.all([loadLibrary(), loadAgents()]).catch(e => { agentsEl.textContent = "加载失败：" + e.message; });
    return () => { if (pollTimer) clearInterval(pollTimer); };
  }

  function renderSearchSettings(root) {
    root.innerHTML = `
      <div class="settings-panel-heading">
        <div>
          <div class="settings-panel-eyebrow">SEARCH</div>
          <h3>搜索设置</h3>
          <p>管理本地搜索与 GBrain hybrid 的切换和索引状态。</p>
        </div>
      </div>
      <div class="search-settings-card">
        <div class="search-settings-row">
          <div>
            <strong>GBrain MCP</strong>
            <div class="settings-help">开启后，搜索会优先使用项目级 GBrain 索引。</div>
          </div>
          <label class="gbrain-toggle" title="仅在 GBrain 索引 ready 后切换 hybrid">
            <input type="checkbox" id="settingsGbrainToggle" /> 开启
          </label>
        </div>
        <div class="search-settings-status" id="settingsGbrainStatus">读取状态中...</div>
        <div class="search-settings-actions">
          <button class="btn-sm" id="settingsGbrainSetup" type="button" style="display:none;">安装 GBrain</button>
          <button class="btn-sm" id="settingsGbrainRebuild" type="button" style="display:none;">重建索引</button>
        </div>
      </div>
      <div class="search-settings-card">
        <div class="search-settings-row">
          <div>
            <strong>必要配置</strong>
            <div class="settings-help">仅保存能被当前适配器验证生效的配置。</div>
          </div>
          <button class="btn-sm" id="settingsGbrainConfigSave" type="button">保存配置</button>
        </div>
        <div class="search-settings-form">
          <label>GBrain 搜索模式
            <select id="settingsGbrainMode">
              <option value="conservative">保守 conservative</option>
              <option value="balanced">平衡 balanced</option>
              <option value="tokenmax">高召回 tokenmax</option>
            </select>
          </label>
          <label>项目结果上限
            <input id="settingsGbrainLimit" type="number" min="1" max="50" step="1" />
          </label>
        </div>
        <div class="search-settings-config-status" id="settingsGbrainConfigStatus">读取配置中...</div>
        <div class="settings-help">当前未开放 token budget、keyword-only：GBrain 当前版本的配置键无法在本适配器中可靠读回验证。</div>
      </div>
    `;

    const toggle = root.querySelector("#settingsGbrainToggle");
    const setup = root.querySelector("#settingsGbrainSetup");
    const rebuild = root.querySelector("#settingsGbrainRebuild");
    const statusEl = root.querySelector("#settingsGbrainStatus");
    const modeEl = root.querySelector("#settingsGbrainMode");
    const limitEl = root.querySelector("#settingsGbrainLimit");
    const configSave = root.querySelector("#settingsGbrainConfigSave");
    const configStatusEl = root.querySelector("#settingsGbrainConfigStatus");
    let poll = null;

    function stopPolling() {
      if (poll) clearInterval(poll);
      poll = null;
    }

    function startPolling() {
      if (!poll) poll = setInterval(loadStatus, 3000);
    }

    function applyStatus(status, runtime) {
      const ready = status?.ready === true && status.backend === "gbrain";
      const runtimeMissing = !runtime || ["missing", "failed", "invalid_configured_runtime", "not_requested"].includes(runtime.status);
      const syncing = ["queued", "syncing"].includes(status?.status) || runtime?.status === "installing";
      toggle.checked = !!status?.enabled;
      toggle.disabled = syncing;
      setup.style.display = !ready && !status?.enabled && runtimeMissing ? "inline-block" : "none";
      setup.textContent = runtime?.status === "missing" || runtime?.status === "not_requested" ? "安装 GBrain" : "修复 GBrain";
      rebuild.style.display = ready && !syncing ? "inline-block" : "none";
      statusEl.textContent = ready ? "当前引擎：GBrain hybrid" : syncing ? "当前引擎：本地搜索（处理中）" : status?.status === "failed" ? "当前引擎：本地搜索（同步失败）" : runtimeMissing ? "当前引擎：本地搜索（GBrain 不可用）" : "当前引擎：本地搜索";
      if (syncing) startPolling(); else stopPolling();
    }

    function applyConfig(config, runtime) {
      const desired = config?.desired || {};
      const effective = config?.effective || {};
      modeEl.value = desired.gbrain_mode || "balanced";
      limitEl.value = desired.result_limit || 20;
      const ready = runtime?.status === "ready";
      modeEl.disabled = !ready;
      limitEl.disabled = false;
      configSave.disabled = !ready;
      if (config?.error) {
        configStatusEl.textContent = "GBrain 配置读取失败：" + config.error;
      } else if (!ready) {
        configStatusEl.textContent = "GBrain 未就绪：可查看项目结果上限，搜索模式需先安装并验证 GBrain。";
      } else if (config?.applied?.gbrain_mode) {
        configStatusEl.textContent = `已生效：${effective.gbrain_mode}；项目结果上限：${desired.result_limit}`;
      } else {
        configStatusEl.textContent = `待应用：${desired.gbrain_mode}；当前 GBrain：${effective.gbrain_mode || "未知"}`;
      }
    }

    async function loadStatus() {
      if (!App.state.projectId) return;
      try {
        const [status, runtime, config] = await Promise.all([
          App.api(`/api/v1/projects/${App.state.projectId}/gbrain-search`),
          App.api(`/api/v1/projects/${App.state.projectId}/gbrain`),
          App.api(`/api/v1/projects/${App.state.projectId}/gbrain-search/config`),
        ]);
        applyStatus(status, runtime);
        applyConfig(config, runtime);
      } catch (e) {
        statusEl.textContent = "状态读取失败：" + e.message;
      }
    }

    configSave.addEventListener("click", async () => {
      if (!window.confirm("保存后会修改 GBrain 实例级搜索模式，可能影响共享该实例的其他项目。继续吗？")) return;
      configSave.disabled = true;
      try {
        await App.api(`/api/v1/projects/${App.state.projectId}/gbrain-search/config`, {
          method: "PUT",
          body: {
            gbrain_mode: modeEl.value,
            result_limit: Number(limitEl.value),
            confirm: true,
          },
        });
        await loadStatus();
        App.toast("GBrain 搜索配置已保存", "success");
      } catch (e) {
        App.toast("GBrain 配置保存失败: " + e.message, "error");
        configSave.disabled = false;
      }
    });

    toggle.addEventListener("change", async () => {
      const enabling = toggle.checked;
      if (enabling && !window.confirm("开启后会复制当前项目 Wiki 到 GBrain，并可能产生 embedding 成本。继续吗？")) {
        toggle.checked = false;
        return;
      }
      toggle.disabled = true;
      try {
        await App.api(`/api/v1/projects/${App.state.projectId}/gbrain-search/${enabling ? "enable" : "disable"}`, {
          method: "POST",
          body: enabling ? { confirm: true } : undefined,
        });
        await loadStatus();
      } catch (e) {
        toggle.checked = !enabling;
        App.toast("GBrain 设置失败: " + e.message, "error");
        toggle.disabled = false;
      }
    });

    setup.addEventListener("click", async () => {
      if (!window.confirm("将从项目配置指定的 reviewed ref 下载并安装 GBrain。继续吗？")) return;
      setup.disabled = true;
      try {
        await App.api(`/api/v1/projects/${App.state.projectId}/gbrain/setup`, { method: "POST", body: { confirm: true } });
        await loadStatus();
      } catch (e) {
        App.toast("GBrain 安装失败: " + e.message, "error");
      } finally {
        setup.disabled = false;
      }
    });

    rebuild.addEventListener("click", async () => {
      if (!window.confirm("将重新同步当前项目 Wiki 到 GBrain。继续吗？")) return;
      rebuild.disabled = true;
      try {
        await App.api(`/api/v1/projects/${App.state.projectId}/gbrain-search/rebuild`, { method: "POST", body: { confirm: true } });
        await loadStatus();
      } catch (e) {
        App.toast("GBrain 重建失败: " + e.message, "error");
      } finally {
        rebuild.disabled = false;
      }
    });

    loadStatus();
    return stopPolling;
  }
})();

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const TAB_ID = "model-uploader";
const API_BASE = "/model-uploader";

let styleElement = null;
let activeInstance = null;

function ensureStyles() {
  if (styleElement) {
    return;
  }

  styleElement = document.createElement("style");
  styleElement.textContent = `
    .cmu-panel {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      color: var(--p-text-color, #f5f5f5);
      background: var(--p-content-background, #111);
      font-size: 13px;
      line-height: 1.35;
    }

    .cmu-panel *,
    .cmu-panel *::before,
    .cmu-panel *::after {
      box-sizing: border-box;
    }

    .cmu-header {
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--p-content-border-color, rgba(255, 255, 255, 0.12));
    }

    .cmu-title {
      min-width: 0;
      font-size: 14px;
      font-weight: 650;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .cmu-actions {
      display: flex;
      align-items: center;
      gap: 6px;
      flex: 0 0 auto;
    }

    .cmu-button {
      appearance: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      min-height: 30px;
      padding: 0 9px;
      border: 1px solid var(--p-button-secondary-border-color, rgba(255, 255, 255, 0.16));
      border-radius: 6px;
      color: var(--p-button-secondary-color, #f5f5f5);
      background: var(--p-button-secondary-background, rgba(255, 255, 255, 0.08));
      font: inherit;
      cursor: pointer;
    }

    .cmu-button:hover:not(:disabled) {
      background: var(--p-button-secondary-hover-background, rgba(255, 255, 255, 0.14));
    }

    .cmu-button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .cmu-button-primary {
      border-color: var(--p-primary-500, #38bdf8);
      color: var(--p-primary-contrast-color, #041018);
      background: var(--p-primary-500, #38bdf8);
    }

    .cmu-button-primary:hover:not(:disabled) {
      background: var(--p-primary-400, #67d5ff);
    }

    .cmu-selected {
      flex: 0 0 auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 3px;
      padding: 9px 12px;
      border-bottom: 1px solid var(--p-content-border-color, rgba(255, 255, 255, 0.12));
      background: color-mix(in srgb, var(--p-content-background, #111) 86%, var(--p-primary-500, #38bdf8));
    }

    .cmu-selected-label {
      color: var(--p-text-muted-color, rgba(255, 255, 255, 0.68));
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .cmu-selected-path {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }

    .cmu-status {
      flex: 0 0 auto;
      min-height: 26px;
      padding: 6px 12px;
      border-bottom: 1px solid var(--p-content-border-color, rgba(255, 255, 255, 0.12));
      color: var(--p-text-muted-color, rgba(255, 255, 255, 0.68));
      overflow-wrap: anywhere;
    }

    .cmu-status[data-kind="error"] {
      color: var(--p-red-300, #fca5a5);
    }

    .cmu-status[data-kind="success"] {
      color: var(--p-green-300, #86efac);
    }

    .cmu-progress {
      flex: 0 0 auto;
      height: 3px;
      background: transparent;
      overflow: hidden;
    }

    .cmu-progress-bar {
      width: 0%;
      height: 100%;
      background: var(--p-primary-500, #38bdf8);
      transition: width 120ms linear;
    }

    .cmu-tree {
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      padding: 6px;
    }

    .cmu-row {
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr) auto;
      align-items: center;
      gap: 4px;
      width: 100%;
      min-height: 30px;
      padding: 3px 6px;
      border: 0;
      border-radius: 6px;
      color: inherit;
      background: transparent;
      font: inherit;
      text-align: left;
    }

    .cmu-row-button {
      cursor: pointer;
    }

    .cmu-row-button:hover {
      background: var(--p-content-hover-background, rgba(255, 255, 255, 0.08));
    }

    .cmu-row[data-selected="true"] {
      background: color-mix(in srgb, var(--p-primary-500, #38bdf8) 22%, transparent);
      color: var(--p-text-color, #fff);
    }

    .cmu-disclosure {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border: 0;
      border-radius: 4px;
      color: var(--p-text-muted-color, rgba(255, 255, 255, 0.68));
      background: transparent;
      cursor: pointer;
      font: inherit;
    }

    .cmu-disclosure:hover {
      background: var(--p-content-hover-background, rgba(255, 255, 255, 0.08));
    }

    .cmu-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .cmu-meta {
      color: var(--p-text-muted-color, rgba(255, 255, 255, 0.58));
      font-size: 11px;
      white-space: nowrap;
    }

    .cmu-children {
      margin-left: 14px;
      border-left: 1px solid var(--p-content-border-color, rgba(255, 255, 255, 0.12));
      padding-left: 4px;
    }

    .cmu-empty {
      padding: 14px 8px;
      color: var(--p-text-muted-color, rgba(255, 255, 255, 0.58));
    }

    .cmu-file-row {
      cursor: default;
      color: var(--p-text-muted-color, rgba(255, 255, 255, 0.78));
    }

    .cmu-file-row .cmu-name {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }
  `;
  document.head.appendChild(styleElement);
}

function createElement(tag, props = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (key === "className") {
      element.className = value;
    } else if (key === "text") {
      element.textContent = value;
    } else if (key === "dataset") {
      Object.assign(element.dataset, value);
    } else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key in element) {
      element[key] = value;
    } else {
      element.setAttribute(key, value);
    }
  }
  for (const child of children) {
    if (child !== null && child !== undefined) {
      element.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
  }
  return element;
}

async function fetchJson(route, options = {}) {
  const response = await api.fetchApi(route, {
    cache: "no-store",
    ...options,
  });

  if (!response.ok) {
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.error || message;
    } catch {
      try {
        message = await response.text();
      } catch {
        // Keep the response status text.
      }
    }
    throw new Error(message);
  }

  return response.json();
}

function formatBytes(value) {
  if (!Number.isFinite(value)) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function formatDate(timestamp) {
  if (!timestamp) {
    return "";
  }
  return new Date(timestamp * 1000).toLocaleString();
}

function nodeKey(modelType, pathIndex, path = "") {
  return `${modelType}|${pathIndex}|${path}`;
}

function selectedLabel(selected) {
  if (!selected) {
    return "No folder selected";
  }
  const suffix = selected.path ? `/${selected.path}` : "";
  return `${selected.modelType}[${selected.pathIndex}]${suffix}`;
}

function safePath(path) {
  return path || "";
}

class ModelUploaderSidebar {
  constructor() {
    this.container = null;
    this.fileInput = null;
    this.refreshButton = null;
    this.uploadButton = null;
    this.treeElement = null;
    this.statusElement = null;
    this.statusTextElement = null;
    this.selectedPathElement = null;
    this.progressBarElement = null;
    this.abortController = null;
    this.state = {
      folders: [],
      expanded: new Set(),
      loaded: new Map(),
      selected: null,
      loading: false,
      uploading: false,
      uploadId: null,
    };
  }

  render(container) {
    ensureStyles();
    if (this.container === container && container.querySelector(".cmu-panel")) {
      return;
    }
    this.destroy();
    this.container = container;
    container.replaceChildren();

    this.fileInput = createElement("input", {
      type: "file",
      hidden: true,
      onchange: () => {
        const file = this.fileInput.files?.[0];
        this.fileInput.value = "";
        if (file) {
          this.uploadFile(file);
        }
      },
    });

    this.refreshButton = createElement(
      "button",
      {
        type: "button",
        className: "cmu-button",
        title: "Refresh",
        onclick: () => this.loadFolders(),
      },
      [
        createElement("span", { className: "icon-[lucide--refresh-cw]", "aria-hidden": "true" }),
        createElement("span", { text: "Refresh" }),
      ],
    );

    this.uploadButton = createElement(
      "button",
      {
        type: "button",
        className: "cmu-button cmu-button-primary",
        title: "Upload",
        disabled: true,
        onclick: () => this.fileInput.click(),
      },
      [
        createElement("span", { className: "icon-[lucide--upload]", "aria-hidden": "true" }),
        createElement("span", { text: "Upload" }),
      ],
    );

    this.selectedPathElement = createElement("div", {
      className: "cmu-selected-path",
      text: selectedLabel(this.state.selected),
      title: selectedLabel(this.state.selected),
    });

    this.statusElement = createElement("div", { className: "cmu-status" });
    this.statusTextElement = createElement("span", { text: "Ready" });
    this.statusElement.appendChild(this.statusTextElement);

    this.progressBarElement = createElement("div", { className: "cmu-progress-bar" });
    const progress = createElement("div", { className: "cmu-progress" }, [this.progressBarElement]);

    this.treeElement = createElement("div", { className: "cmu-tree" });

    const panel = createElement("div", { className: "cmu-panel" }, [
      createElement("div", { className: "cmu-header" }, [
        createElement("div", { className: "cmu-title", text: "Model Uploads" }),
        createElement("div", { className: "cmu-actions" }, [this.refreshButton, this.uploadButton]),
      ]),
      createElement("div", { className: "cmu-selected" }, [
        createElement("div", { className: "cmu-selected-label", text: "Destination" }),
        this.selectedPathElement,
      ]),
      this.statusElement,
      progress,
      this.treeElement,
      this.fileInput,
    ]);

    container.appendChild(panel);
    this.loadFolders();
  }

  destroy() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    if (this.container) {
      this.container.replaceChildren();
      this.container = null;
    }
  }

  setStatus(message, kind = "") {
    if (!this.statusTextElement || !this.statusElement) {
      return;
    }
    this.statusTextElement.textContent = message;
    this.statusElement.dataset.kind = kind;
  }

  setProgress(value) {
    if (!this.progressBarElement) {
      return;
    }
    const percent = Math.max(0, Math.min(100, value));
    this.progressBarElement.style.width = `${percent}%`;
  }

  updateControls() {
    if (this.uploadButton) {
      this.uploadButton.disabled = !this.state.selected || this.state.uploading;
    }
    if (this.refreshButton) {
      this.refreshButton.disabled = this.state.loading || this.state.uploading;
    }
    if (this.selectedPathElement) {
      const label = selectedLabel(this.state.selected);
      this.selectedPathElement.textContent = label;
      this.selectedPathElement.title = label;
    }
  }

  async loadFolders() {
    this.state.loading = true;
    this.updateControls();
    this.setStatus("Loading model folders");
    try {
      const payload = await fetchJson(`${API_BASE}/folders`);
      this.state.folders = payload.folders || [];
      this.state.loaded.clear();
      this.state.expanded.clear();
      this.renderTree();
      this.setStatus(`${this.state.folders.length} model folders`, "success");
    } catch (error) {
      this.setStatus(error.message || String(error), "error");
    } finally {
      this.state.loading = false;
      this.updateControls();
    }
  }

  async loadNode(modelType, pathIndex, path = "") {
    const key = nodeKey(modelType, pathIndex, path);
    const params = new URLSearchParams({
      model_type: modelType,
      path_index: String(pathIndex),
      path: safePath(path),
    });

    this.setStatus(`Loading ${modelType}`);
    const payload = await fetchJson(`${API_BASE}/tree?${params.toString()}`);
    this.state.loaded.set(key, payload);
    return payload;
  }

  async toggleNode(modelType, pathIndex, path = "") {
    const key = nodeKey(modelType, pathIndex, path);
    if (this.state.expanded.has(key)) {
      this.state.expanded.delete(key);
      this.renderTree();
      return;
    }

    this.state.expanded.add(key);
    this.renderTree();
    if (!this.state.loaded.has(key)) {
      try {
        await this.loadNode(modelType, pathIndex, path);
        this.setStatus("Ready");
      } catch (error) {
        this.state.expanded.delete(key);
        this.setStatus(error.message || String(error), "error");
      }
    }
    this.renderTree();
  }

  selectFolder(modelType, pathIndex, path = "") {
    this.state.selected = { modelType, pathIndex, path: safePath(path) };
    this.updateControls();
    this.renderTree();
  }

  renderTree() {
    if (!this.treeElement) {
      return;
    }

    this.treeElement.replaceChildren();
    if (this.state.folders.length === 0) {
      this.treeElement.appendChild(createElement("div", { className: "cmu-empty", text: "No model folders" }));
      return;
    }

    for (const folder of this.state.folders) {
      this.treeElement.appendChild(this.renderModelType(folder));
    }
  }

  renderModelType(folder) {
    const wrapper = createElement("div");
    const roots = folder.roots || [];
    const singleRoot = roots.length === 1;
    const modelTypeKey = nodeKey(folder.name, -1, "__model_type__");
    const expanded = this.state.expanded.has(modelTypeKey);

    const row = createElement("button", {
      type: "button",
      className: "cmu-row cmu-row-button",
      onclick: () => {
        if (singleRoot && roots[0]) {
          this.toggleNode(folder.name, roots[0].pathIndex, "");
          this.selectFolder(folder.name, roots[0].pathIndex, "");
        } else {
          if (expanded) {
            this.state.expanded.delete(modelTypeKey);
          } else {
            this.state.expanded.add(modelTypeKey);
          }
          this.renderTree();
        }
      },
    });

    const disclosure = createElement("span", {
      className: "cmu-disclosure",
      text: singleRoot ? (this.state.expanded.has(nodeKey(folder.name, roots[0]?.pathIndex ?? 0, "")) ? "v" : ">") : expanded ? "v" : ">",
    });
    const name = createElement("span", { className: "cmu-name", text: folder.name, title: folder.name });
    const meta = createElement("span", { className: "cmu-meta", text: `${roots.length}` });
    row.append(disclosure, name, meta);
    wrapper.appendChild(row);

    if (singleRoot) {
      const root = roots[0];
      const key = nodeKey(folder.name, root.pathIndex, "");
      if (this.state.expanded.has(key)) {
        wrapper.appendChild(this.renderLoadedNode(folder.name, root.pathIndex, "", root));
      }
    } else if (expanded) {
      const children = createElement("div", { className: "cmu-children" });
      for (const root of roots) {
        children.appendChild(this.renderRootRow(folder.name, root));
      }
      wrapper.appendChild(children);
    }

    return wrapper;
  }

  renderRootRow(modelType, root) {
    const wrapper = createElement("div");
    const key = nodeKey(modelType, root.pathIndex, "");
    const expanded = this.state.expanded.has(key);
    const selected = this.isSelected(modelType, root.pathIndex, "");
    const row = createElement("button", {
      type: "button",
      className: "cmu-row cmu-row-button",
      dataset: { selected: selected ? "true" : "false" },
      title: root.path,
      onclick: () => {
        this.selectFolder(modelType, root.pathIndex, "");
        this.toggleNode(modelType, root.pathIndex, "");
      },
    });
    row.append(
      createElement("span", { className: "cmu-disclosure", text: expanded ? "v" : ">" }),
      createElement("span", { className: "cmu-name", text: root.path, title: root.path }),
      createElement("span", { className: "cmu-meta", text: root.exists ? "" : "new" }),
    );
    wrapper.appendChild(row);

    if (expanded) {
      wrapper.appendChild(this.renderLoadedNode(modelType, root.pathIndex, "", root));
    }
    return wrapper;
  }

  renderLoadedNode(modelType, pathIndex, path, root = null) {
    const key = nodeKey(modelType, pathIndex, path);
    const container = createElement("div", { className: "cmu-children" });
    const payload = this.state.loaded.get(key);

    if (!payload) {
      container.appendChild(createElement("div", { className: "cmu-empty", text: "Loading" }));
      return container;
    }

    if (root && !root.exists && path === "") {
      container.appendChild(createElement("div", { className: "cmu-empty", text: "Folder will be created on upload" }));
      return container;
    }

    const dirs = payload.dirs || [];
    const files = payload.files || [];

    if (dirs.length === 0 && files.length === 0) {
      container.appendChild(createElement("div", { className: "cmu-empty", text: "Empty folder" }));
      return container;
    }

    for (const dir of dirs) {
      container.appendChild(this.renderFolderRow(modelType, pathIndex, dir));
    }
    for (const file of files) {
      container.appendChild(this.renderFileRow(file));
    }
    return container;
  }

  renderFolderRow(modelType, pathIndex, dir) {
    const wrapper = createElement("div");
    const key = nodeKey(modelType, pathIndex, dir.path);
    const expanded = this.state.expanded.has(key);
    const selected = this.isSelected(modelType, pathIndex, dir.path);
    const row = createElement("button", {
      type: "button",
      className: "cmu-row cmu-row-button",
      dataset: { selected: selected ? "true" : "false" },
      title: dir.path,
      onclick: () => {
        this.selectFolder(modelType, pathIndex, dir.path);
        this.toggleNode(modelType, pathIndex, dir.path);
      },
    });
    row.append(
      createElement("span", { className: "cmu-disclosure", text: expanded ? "v" : ">" }),
      createElement("span", { className: "cmu-name", text: dir.name, title: dir.path }),
      createElement("span", { className: "cmu-meta", text: formatDate(dir.modified) }),
    );
    wrapper.appendChild(row);
    if (expanded) {
      wrapper.appendChild(this.renderLoadedNode(modelType, pathIndex, dir.path));
    }
    return wrapper;
  }

  renderFileRow(file) {
    const row = createElement("div", {
      className: "cmu-row cmu-file-row",
      title: file.path,
    });
    row.append(
      createElement("span", { className: "cmu-disclosure", text: "" }),
      createElement("span", { className: "cmu-name", text: file.name, title: file.path }),
      createElement("span", { className: "cmu-meta", text: formatBytes(file.size) }),
    );
    return row;
  }

  isSelected(modelType, pathIndex, path) {
    const selected = this.state.selected;
    return Boolean(selected && selected.modelType === modelType && selected.pathIndex === pathIndex && selected.path === safePath(path));
  }

  async uploadFile(file) {
    const selected = this.state.selected;
    if (!selected || this.state.uploading) {
      return;
    }

    this.state.uploading = true;
    this.abortController = new AbortController();
    this.setProgress(0);
    this.setStatus(`Preparing ${file.name}`);
    this.updateControls();

    let uploadId = null;
    let finalName = file.name;
    try {
      const init = await fetchJson(`${API_BASE}/upload/init`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          modelType: selected.modelType,
          pathIndex: selected.pathIndex,
          subfolder: selected.path,
          filename: file.name,
          size: file.size,
        }),
        signal: this.abortController.signal,
      });

      uploadId = init.uploadId;
      this.state.uploadId = uploadId;
      const chunkSize = init.chunkSize || 32 * 1024 * 1024;

      if (file.size === 0) {
        const completed = await this.completeUpload(uploadId);
        finalName = completed.finalName || finalName;
      } else {
        let offset = 0;
        while (offset < file.size) {
          const chunk = file.slice(offset, Math.min(offset + chunkSize, file.size));
          const response = await api.fetchApi(`${API_BASE}/upload/chunk/${encodeURIComponent(uploadId)}`, {
            method: "POST",
            headers: {
              "Content-Type": "application/octet-stream",
              "X-Upload-Offset": String(offset),
            },
            body: chunk,
            cache: "no-store",
            signal: this.abortController.signal,
          });

          if (!response.ok) {
            let message = response.statusText || `HTTP ${response.status}`;
            try {
              const payload = await response.json();
              message = payload.error || message;
            } catch {
              // Keep status text.
            }
            throw new Error(message);
          }

          const payload = await response.json();
          offset = payload.received;
          this.setProgress((offset / file.size) * 100);
          this.setStatus(`Uploading ${file.name} ${formatBytes(offset)} / ${formatBytes(file.size)}`);
        }

        const completed = await this.completeUpload(uploadId);
        finalName = completed.finalName || finalName;
      }

      this.setProgress(100);
      await this.refreshSelectedFolder();
      this.setStatus(`Uploaded ${finalName}`, "success");
      this.refreshComfyModels();
    } catch (error) {
      if (uploadId) {
        await api.fetchApi(`${API_BASE}/upload/cancel/${encodeURIComponent(uploadId)}`, {
          method: "POST",
          cache: "no-store",
        }).catch(() => {});
      }
      if (error.name === "AbortError") {
        this.setStatus("Upload canceled", "error");
      } else {
        this.setStatus(error.message || String(error), "error");
      }
      this.setProgress(0);
    } finally {
      this.state.uploading = false;
      this.state.uploadId = null;
      this.abortController = null;
      this.updateControls();
    }
  }

  async completeUpload(uploadId) {
    return fetchJson(`${API_BASE}/upload/complete/${encodeURIComponent(uploadId)}`, {
      method: "POST",
      signal: this.abortController?.signal,
    });
  }

  async refreshSelectedFolder() {
    const selected = this.state.selected;
    if (!selected) {
      return;
    }
    const key = nodeKey(selected.modelType, selected.pathIndex, selected.path);
    this.state.loaded.delete(key);
    try {
      await this.loadNode(selected.modelType, selected.pathIndex, selected.path);
    } catch (error) {
      this.setStatus(error.message || String(error), "error");
    }
    this.renderTree();
  }

  refreshComfyModels() {
    try {
      app.extensionManager?.command?.execute?.("Comfy.RefreshNodeDefinitions", {
        errorHandler: () => {},
      });
    } catch {
      // Upload has already succeeded; a manual Comfy refresh can still pick it up.
    }
  }
}

app.registerExtension({
  name: "Comfy.ModelUploader",
  setup() {
    const manager = app.extensionManager;
    if (!manager?.registerSidebarTab) {
      console.warn("Comfy Model Uploader requires a ComfyUI frontend with custom sidebar tabs.");
      return;
    }

    try {
      manager.unregisterSidebarTab?.(TAB_ID);
    } catch {
      // If the tab was not registered yet, continue with normal registration.
    }

    activeInstance = new ModelUploaderSidebar();
    manager.registerSidebarTab({
      id: TAB_ID,
      title: "Model Uploads",
      tooltip: "Model Uploads",
      icon: "icon-[lucide--upload-cloud]",
      type: "custom",
      render: (container) => activeInstance.render(container),
      destroy: () => activeInstance.destroy(),
    });
  },
});

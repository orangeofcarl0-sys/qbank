import { ask, open, save as chooseSavePath } from "@tauri-apps/plugin-dialog";
import { diff_match_patch } from "diff-match-patch";
import Vditor from "vditor";
import { SidecarRpcError, TauriRpcBridge } from "./bridge";
import { EditorBuffer, type EditorMode } from "./editor-buffer";
import { icon } from "./icons";
import {
  guardMathSource,
  sanitizePreviewHtml,
  sanitizeSvgDataUrl,
  SecurePreviewFrame,
} from "./secure-preview";
import {
  bodyForPreview,
  insertAssetReference,
  nextAssetId,
  rewriteBackslashMathHtml,
} from "./markdown";
import {
  displayTag,
  EMPTY_FILTERS,
  facetValues,
  filterChips,
  filtersEqual,
  filtersToRpc,
  normalizeFilters,
  removeFilterChip,
  type QueryFilters,
  type SavedView,
  type TagOverview,
  type TagUsage,
  type TaxonomyTag,
} from "./advanced-management";
import type {
  AssetItem,
  HistoryEntry,
  InitializeResult,
  JsonValue,
  PaperDocument,
  PaperSummary,
  PaperValidationResult,
  QuestionDocument,
  QuestionMutationResult,
  QuestionSummary,
  RepositoryOpenResult,
  RepositoryStatus,
  RpcBridge,
  SaveResult,
  ValidationResult,
} from "./protocol";

interface AppState {
  initialized: InitializeResult | null;
  repository: RepositoryStatus | null;
  questions: QuestionSummary[];
  visibleQuestions: QuestionSummary[];
  current: QuestionDocument | null;
  assets: AssetItem[];
  history: HistoryEntry[];
  mode: EditorMode;
  theme: "light" | "dark";
  loading: boolean;
  validation: ValidationResult | null;
  selectedQuestionIds: Set<string>;
  currentPaper: PaperDocument | null;
  papers: PaperSummary[];
  searchText: string;
  filters: QueryFilters;
  views: SavedView[];
  tags: TagUsage[];
  selectedView: string;
  selectedViewBaseline: QueryFilters | null;
  specialViewIds: Set<string> | null;
}

const EMPTY_STATE: AppState = {
  initialized: null,
  repository: null,
  questions: [],
  visibleQuestions: [],
  current: null,
  assets: [],
  history: [],
  mode: "split",
  theme: "light",
  loading: false,
  validation: null,
  selectedQuestionIds: new Set(),
  currentPaper: null,
  papers: [],
  searchText: "",
  filters: normalizeFilters(EMPTY_FILTERS),
  views: [],
  tags: [],
  selectedView: "all",
  selectedViewBaseline: normalizeFilters(EMPTY_FILTERS),
  specialViewIds: null,
};

const COMMON_MATH_MACROS: Record<string, string | [string, number]> = {
  RR: "\\mathbb{R}",
  NN: "\\mathbb{N}",
  ZZ: "\\mathbb{Z}",
  QQ: "\\mathbb{Q}",
  CC: "\\mathbb{C}",
  abs: ["\\left|#1\\right|", 1],
  norm: ["\\left\\lVert#1\\right\\rVert", 1],
  qbankasset: "\\mathrm{asset}",
};

export class StudioApp {
  private readonly bridge: RpcBridge;
  private readonly buffer = new EditorBuffer();
  private state: AppState = { ...EMPTY_STATE, selectedQuestionIds: new Set() };
  private editor: Vditor | null = null;
  private editorReady = false;
  private editorGeneration = 0;
  private editorProjection = "";
  private projectionSources = new Map<string, string>();
  private readonly projectionPatcher = new diff_match_patch();
  private previewBindings = new Map<string, string>();
  private preview: SecurePreviewFrame | null = null;
  private previewGeneration = 0;
  private previewTimer = 0;
  private searchTimer = 0;
  private repositoryGeneration = 0;

  constructor(
    private readonly root: HTMLElement,
    bridge: RpcBridge = new TauriRpcBridge(),
  ) {
    this.bridge = bridge;
  }

  async start(): Promise<void> {
    this.renderShell();
    this.preview = new SecurePreviewFrame(
      this.element("editor-frame"),
      (event, formula) => this.showFormulaMenuFromPreview(event, formula),
    );
    this.preview.clear(this.state.theme);
    this.bindStaticActions();
    this.bridge.onExit((reason) => this.showSidecarFailure(reason));
    try {
      this.state.initialized = await this.bridge.start();
      this.setConnection("已连接", "success");
      this.renderAbout();
    } catch (error) {
      this.showSidecarFailure(error instanceof Error ? error.message : String(error));
    }
  }

  /** Deterministic browser-harness surface; it does not mutate repositories directly. */
  testSnapshot(): { buffer: string; editor: string | null; dirty: boolean } {
    const snapshot = this.buffer.snapshot();
    return {
      buffer: snapshot.source,
      editor: this.editorReady ? this.editor?.getValue() ?? null : null,
      dirty: snapshot.dirty,
    };
  }

  /** Deterministic browser-harness input using the same Vditor API as production. */
  testSetEditorValue(source: string): void {
    if (!this.editorReady) return;
    this.applyEditorProjection(source);
    this.editor?.setValue(source, true);
    this.scheduleSecurePreview();
  }

  /** Browser security harness for the same sanitizer used by production previews. */
  testSanitizeSvgDataUrl(value: string): string | null {
    return sanitizeSvgDataUrl(value);
  }

  private renderShell(): void {
    this.root.innerHTML = `
      <div class="app-shell" data-theme="light">
        <header class="titlebar">
          <div class="brand"><span class="brand-mark">Q</span><strong>QBank Studio</strong><span class="version">0.3.0-beta.2</span></div>
          <div class="repository-identity"><button id="copy-repository-path" class="repository-copy" type="button" disabled title="复制题库路径"><strong id="repository-name">未打开题库</strong><small id="repository-path">选择题库后可复制路径</small></button><span id="repository-health" class="health neutral">等待连接</span></div>
          <button id="theme-toggle" class="icon-button" aria-label="切换浅色或深色主题" title="切换主题">${icon("sun")}</button>
        </header>
        <div class="workspace">
          <aside class="navigation" aria-label="题目导航">
            <div class="nav-header">
              <button id="open-repository" class="primary-button">${icon("folder")}<span>打开题库</span></button>
              <div class="question-actions" role="toolbar" aria-label="题目管理">
                <button id="new-question" class="compact-button" disabled>新建</button>
                <button id="copy-question" class="compact-button" disabled>复制</button>
                <button id="import-questions" class="compact-button" disabled>导入</button>
                <button id="delete-question" class="compact-button danger" disabled>删除</button>
              </div>
              <div class="view-row">
                <label><span>视图</span><select id="saved-view-select" aria-label="保存视图" disabled><option value="all">全部题目</option></select></label>
                <button id="save-view" class="icon-button" disabled title="保存当前筛选" aria-label="保存当前筛选">${icon("save")}</button>
                <button id="view-menu" class="icon-button" disabled title="管理当前视图" aria-label="管理当前视图">${icon("more")}</button>
              </div>
              <label class="search-box" aria-label="搜索题目">${icon("search")}<input id="search-input" type="search" placeholder="搜索标题、ID 或正文" disabled /></label>
              <div id="filter-chips" class="filter-chips" aria-label="当前筛选"></div>
              <details id="advanced-filters" class="advanced-filters">
                <summary>筛选与标签 <span id="active-filter-count">0</span></summary>
                <div class="facet-grid" aria-label="字段分面">
                  <label><span>状态</span><select id="status-filter" aria-label="状态" disabled><option value="">全部</option></select></label>
                  <label><span>题型</span><select id="type-filter" aria-label="题型" disabled><option value="">全部</option></select></label>
                  <label><span>学科</span><select id="subject-filter" aria-label="学科" disabled><option value="">全部</option></select></label>
                  <label><span>章节</span><select id="chapter-filter" aria-label="章节" disabled><option value="">全部</option></select></label>
                  <label><span>年份</span><select id="year-filter" aria-label="年份" disabled><option value="">全部</option></select></label>
                  <label><span>语言</span><select id="language-filter" aria-label="语言" disabled><option value="">全部</option></select></label>
                  <label><span>最低难度</span><select id="difficulty-min-filter" aria-label="最低难度" disabled><option value="">不限</option></select></label>
                  <label><span>最高难度</span><select id="difficulty-max-filter" aria-label="最高难度" disabled><option value="">不限</option></select></label>
                </div>
                <div class="tag-filter-controls">
                  <label class="search-box"><span class="sr-only">搜索标签</span>${icon("search")}<input id="tag-filter-search" type="search" placeholder="查找标签" disabled /></label>
                  <label>匹配<select id="topic-mode" aria-label="标签匹配方式" disabled><option value="and">全部（AND）</option><option value="or">任一（OR）</option></select></label>
                </div>
                <div id="tag-filter-list" class="tag-filter-list" aria-label="标签筛选"></div>
                <div class="filter-footer">
                  <button id="tag-manager" class="compact-button" disabled>管理标签</button>
                  <button id="tag-overview" class="compact-button" disabled>统计视图</button>
                  <button id="clear-filters" class="compact-button" disabled>清除全部</button>
                </div>
              </details>
              <div class="result-summary"><span id="result-count">0 题</span><span id="connection-status" class="connection">正在启动…</span></div>
            </div>
            <div id="question-list" class="question-list" role="listbox" aria-label="题目列表">
              <div class="empty-state">打开一个 qbank 题库开始编辑</div>
            </div>
            <div id="batch-bar" class="batch-bar" hidden>
              <strong id="batch-summary">已选择 0 道题</strong>
              <div><button id="batch-tag" disabled>标签</button><button id="batch-status" disabled>状态</button><button id="batch-chapter" disabled>章节</button><button id="batch-paper" disabled>加入试卷</button><button id="batch-clear">取消选择</button></div>
            </div>
          </aside>
          <main class="document-workspace">
            <div class="document-toolbar" role="toolbar" aria-label="文档操作">
              <div class="mode-group" role="group" aria-label="编辑模式">
                <button class="mode-button" data-mode="source" title="Markdown 源码模式">${icon("source")}<span>源码</span></button>
                <button class="mode-button active" data-mode="split" title="源码与预览分栏">${icon("split")}<span>分栏</span></button>
                <button class="mode-button" data-mode="instant" title="即时渲染模式">${icon("preview")}<span>即时</span></button>
              </div>
              <span class="toolbar-separator"></span>
              <button id="undo" class="toolbar-button" disabled title="撤销 Ctrl+Z">${icon("undo")}<span>撤销</span></button>
              <button id="validate" class="toolbar-button" disabled title="校验当前题目">${icon("check")}<span>校验</span></button>
              <button id="paper-manager" class="toolbar-button" disabled title="试卷选择、校验与导出"><span>试卷</span></button>
              <button id="save" class="toolbar-button primary-action" disabled title="保存 Ctrl+S">${icon("save")}<span>保存</span></button>
              <span id="dirty-indicator" class="dirty-indicator">未加载</span>
            </div>
            <section class="document-header">
              <div><h1 id="document-title">选择一道题目</h1><p id="document-identity">源码是权威缓冲区，预览不会改写 Markdown。</p></div>
              <div id="validation-badge" class="validation-badge neutral">尚未校验</div>
            </section>
            <div id="editor-frame" class="editor-frame empty">
              <div id="loading-overlay" class="loading-overlay" hidden><span class="spinner"></span><strong>正在加载题目…</strong></div>
              <div id="preview-progress" class="preview-progress" hidden><span class="spinner"></span><span>正在渲染公式…</span></div>
              <div id="vditor"></div>
              <div id="editor-empty" class="editor-empty">从左侧选择题目</div>
            </div>
            <div id="diagnostic-bar" class="diagnostic-bar" hidden></div>
          </main>
          <aside class="inspector" aria-label="题目详情">
            <div class="inspector-title"><strong>题目详情</strong><span id="inspector-id">—</span></div>
            <section class="inspector-section"><h2>基础属性</h2><form id="metadata-form" class="metadata-form"><p class="muted">未加载</p></form></section>
            <section class="inspector-section"><h2>图形资产</h2><div id="asset-list" class="asset-list"><p class="muted">未加载</p></div></section>
            <section class="inspector-section history-section"><h2>最近历史</h2><div id="history-list" class="history-list"><p class="muted">未加载</p></div></section>
          </aside>
        </div>
        <dialog id="question-dialog" class="native-like-dialog">
          <form method="dialog">
            <h2 id="question-dialog-title">新建题目</h2>
            <label>题目 ID<input id="question-dialog-id" required pattern="[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+" /></label>
            <label id="question-dialog-title-row">标题<input id="question-dialog-name" required /></label>
            <div class="dialog-actions"><button value="cancel">取消</button><button id="question-dialog-confirm" class="primary-button" value="confirm">继续</button></div>
          </form>
        </dialog>
        <dialog id="paper-dialog" class="native-like-dialog paper-dialog">
          <form method="dialog">
            <div class="dialog-heading"><h2>试卷</h2><button value="cancel" aria-label="关闭">×</button></div>
            <label>当前试卷<select id="paper-select"></select></label>
            <div id="paper-summary" class="paper-summary">尚未选择试卷</div>
            <div class="paper-actions">
              <button id="paper-create" type="button">从所选题目新建</button>
              <button id="paper-add" type="button">加入所选题目</button>
              <button id="paper-save" type="button">保存顺序与分值</button>
              <button id="paper-validate" type="button">校验</button>
              <button id="paper-export-student" type="button" class="primary-button">导出学生版</button>
              <button id="paper-export-solution" type="button">导出答案版</button>
            </div>
            <div id="paper-diagnostics" class="paper-diagnostics" aria-live="polite"></div>
          </form>
        </dialog>
        <dialog id="text-action-dialog" class="native-like-dialog compact-dialog">
          <form method="dialog">
            <h2 id="text-action-title">操作</h2>
            <p id="text-action-description" class="muted"></p>
            <label id="text-action-primary-row"><span id="text-action-primary-label">值</span><input id="text-action-primary" /></label>
            <label id="text-action-secondary-row" hidden><span id="text-action-secondary-label">目标</span><input id="text-action-secondary" /></label>
            <datalist id="text-action-tag-suggestions"></datalist>
            <div class="dialog-actions"><button value="cancel">取消</button><button class="primary-button" value="confirm">继续</button></div>
          </form>
        </dialog>
        <dialog id="dirty-state-dialog" class="native-like-dialog compact-dialog">
          <form method="dialog">
            <h2>未保存的修改</h2>
            <p id="dirty-state-description" class="muted">继续前需要处理当前题目的修改。</p>
            <div class="dialog-actions three-actions">
              <button value="cancel">取消</button>
              <button value="discard">放弃修改</button>
              <button class="primary-button" value="save">保存并继续</button>
            </div>
          </form>
        </dialog>
        <dialog id="view-action-dialog" class="native-like-dialog compact-dialog">
          <form method="dialog">
            <h2>管理视图</h2>
            <p id="view-action-description" class="muted"></p>
            <label>操作<select id="view-action-kind"><option value="update">用当前条件更新</option><option value="rename">重命名</option><option value="delete">删除</option><option value="restore">恢复原条件</option></select></label>
            <label id="view-action-name-row">新名称<input id="view-action-name" /></label>
            <div class="dialog-actions"><button value="cancel">取消</button><button class="primary-button" value="confirm">继续</button></div>
          </form>
        </dialog>
        <dialog id="tag-manager-dialog" class="native-like-dialog management-dialog">
          <form method="dialog">
            <div class="dialog-heading"><h2>标签注册表</h2><button value="cancel" aria-label="关闭">×</button></div>
            <label class="search-box">${icon("search")}<input id="tag-manager-search" type="search" placeholder="搜索名称、别名或 slug" /></label>
            <div id="tag-manager-list" class="management-list"></div>
            <div class="dialog-actions"><button id="tag-create" type="button">新建标签</button><button value="cancel">完成</button></div>
          </form>
        </dialog>
        <dialog id="tag-editor-dialog" class="native-like-dialog compact-dialog">
          <form method="dialog">
            <h2 id="tag-editor-title">编辑标签</h2>
            <label>Slug<input id="tag-editor-slug" required pattern="[a-z0-9][a-z0-9._-]*" /></label>
            <label>中文显示名<input id="tag-editor-name-zh" /></label>
            <label>英文显示名<input id="tag-editor-name-en" /></label>
            <label>别名（逗号分隔）<input id="tag-editor-aliases" /></label>
            <label>说明<textarea id="tag-editor-description" rows="3"></textarea></label>
            <label>状态<select id="tag-editor-status"><option value="active">active</option><option value="pending">pending</option><option value="deprecated">deprecated</option></select></label>
            <div class="dialog-actions"><button value="cancel">取消</button><button class="primary-button" value="confirm">保存</button></div>
          </form>
        </dialog>
        <dialog id="tag-overview-dialog" class="native-like-dialog overview-dialog">
          <form method="dialog">
            <div class="dialog-heading"><h2>标签覆盖</h2><button value="cancel" aria-label="关闭">×</button></div>
            <p class="muted">点击频次、共现或覆盖单元格，将其转换为真实题目筛选。</p>
            <div id="tag-overview-content" class="overview-content"></div>
          </form>
        </dialog>
        <div id="toast-region" class="toast-region" aria-live="polite"></div>
      </div>`;
  }

  private bindStaticActions(): void {
    this.element("open-repository").addEventListener("click", () => void this.chooseRepository());
    this.element("copy-repository-path").addEventListener("click", () => {
      const root = this.state.repository?.root;
      if (root !== undefined) void this.copyText(root, "题库路径");
    });
    this.element("theme-toggle").addEventListener("click", () => this.toggleTheme());
    this.element("search-input").addEventListener("input", (event) => {
      window.clearTimeout(this.searchTimer);
      const value = (event.target as HTMLInputElement).value;
      this.state.searchText = value;
      this.state.filters.text = value;
      this.markViewModified();
      this.searchTimer = window.setTimeout(() => void this.refreshFilteredQuestions(), 160);
    });
    for (const id of [
      "status-filter", "type-filter", "subject-filter", "chapter-filter", "year-filter",
      "language-filter", "difficulty-min-filter", "difficulty-max-filter", "topic-mode",
    ]) {
      this.element(id).addEventListener("change", () => {
        this.readFilterControls();
        this.markViewModified();
        void this.refreshFilteredQuestions();
      });
    }
    this.element("saved-view-select").addEventListener("change", () => void this.selectSavedView());
    this.element("save-view").addEventListener("click", () => void this.saveCurrentView());
    this.element("view-menu").addEventListener("click", () => void this.manageCurrentView());
    this.element("clear-filters").addEventListener("click", () => void this.clearFilters());
    this.element("tag-filter-search").addEventListener("input", () => this.renderTagFilters());
    this.element("tag-manager").addEventListener("click", () => this.openTagManager());
    this.element("tag-manager-search").addEventListener("input", () => this.renderTagManager());
    this.element("tag-create").addEventListener("click", () => void this.editTag());
    this.element("tag-overview").addEventListener("click", () => void this.openTagOverview());
    this.element("new-question").addEventListener("click", () => void this.createQuestion());
    this.element("copy-question").addEventListener("click", () => void this.copyQuestion());
    this.element("import-questions").addEventListener("click", () => void this.importQuestions());
    this.element("delete-question").addEventListener("click", () => void this.deleteQuestion());
    this.element("paper-manager").addEventListener("click", () => void this.openPaperManager());
    this.element("paper-select").addEventListener("change", () => void this.selectPaper());
    this.element("paper-create").addEventListener("click", () => void this.createPaper());
    this.element("paper-add").addEventListener("click", () => void this.addSelectedToPaper());
    this.element("paper-save").addEventListener("click", () => void this.savePaper());
    this.element("paper-validate").addEventListener("click", () => void this.validatePaper());
    this.element("paper-export-student").addEventListener("click", () => void this.exportPaper(false));
    this.element("paper-export-solution").addEventListener("click", () => void this.exportPaper(true));
    this.element("batch-tag").addEventListener("click", () => void this.bulkEditTags());
    this.element("batch-status").addEventListener("click", () => void this.bulkUpdateField("status"));
    this.element("batch-chapter").addEventListener("click", () => void this.bulkUpdateField("chapter"));
    this.element("batch-paper").addEventListener("click", () => void this.openPaperManager());
    this.element("batch-clear").addEventListener("click", () => {
      this.state.selectedQuestionIds.clear();
      this.renderQuestions();
    });
    this.element("metadata-form").addEventListener("submit", (event) => {
      event.preventDefault();
      void this.saveMetadata();
    });
    for (const button of this.root.querySelectorAll<HTMLButtonElement>(".mode-button")) {
      button.addEventListener("click", () => this.setMode(button.dataset.mode as EditorMode));
    }
    this.element("save").addEventListener("click", () => void this.save());
    this.element("validate").addEventListener("click", () => void this.validate());
    this.element("undo").addEventListener("click", () => document.execCommand("undo"));
    window.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void this.save();
      }
    });
    const frame = this.element("editor-frame");
    frame.addEventListener("paste", (event) => void this.handlePaste(event as ClipboardEvent), true);
    frame.addEventListener("dragover", (event) => {
      event.preventDefault();
      frame.classList.add("drag-active");
    });
    frame.addEventListener("dragleave", () => frame.classList.remove("drag-active"));
    frame.addEventListener("drop", (event) => void this.handleDrop(event as DragEvent), true);
    frame.addEventListener("contextmenu", (event) => this.showFormulaMenu(event), true);
    document.addEventListener("pointerdown", (event) => {
      if (!(event.target instanceof Element) || event.target.closest(".formula-menu") === null) {
        this.root.querySelector(".formula-menu")?.remove();
      }
      if (!(event.target instanceof Element) || event.target.closest(".asset-card") === null) {
        for (const menu of this.root.querySelectorAll<HTMLElement>(".asset-menu")) menu.hidden = true;
      }
    });
  }

  private async chooseRepository(): Promise<void> {
    const selected = await open({ directory: true, multiple: false, title: "打开 qbank 题库" });
    if (typeof selected === "string") await this.openRepository(selected);
  }

  async openRepository(root: string): Promise<void> {
    if (!(await this.resolveDirtyState("切换题库"))) return;
    const generation = ++this.repositoryGeneration;
    this.setRepositoryLoading("正在检查题库…", "阶段 1/3 · 配置与索引");
    try {
      let opened: RepositoryOpenResult;
      try {
        opened = await this.bridge.request<RepositoryOpenResult>("repository.open", { root });
      } catch (error) {
        if (!isRepairableIndexError(error)) throw error;
        const rebuild = await ask(
          "该题库的搜索索引缺失、损坏或已过期。是否立即重建索引并打开？",
          {
            title: "需要重建搜索索引",
            kind: "warning",
            okLabel: "重建并打开",
            cancelLabel: "取消",
          },
        );
        if (!rebuild || generation !== this.repositoryGeneration) return;
        this.setRepositoryLoading("正在重建搜索索引…", "阶段 2/3 · 可重建投影");
        opened = await this.bridge.request<RepositoryOpenResult>("repository.rebuildIndex", {
          root,
        });
      }
      if (generation !== this.repositoryGeneration) return;
      this.setRepositoryLoading(
        `正在读取 ${opened.questionCount} 道题…`,
        `阶段 2/3 · 索引${opened.indexDirty ? "待恢复" : "正常"}`,
      );
      this.setRepositoryLoading("正在构建导航…", "阶段 3/3 · 分面与标签");
      this.activateRepository(opened);
      this.toast(
        opened.indexed === undefined
          ? `已打开 ${opened.name}`
          : `已重建 ${opened.indexed} 条索引并打开 ${opened.name}`,
        "success",
      );
    } catch (error) {
      if (generation !== this.repositoryGeneration) return;
      this.toast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      if (generation === this.repositoryGeneration) {
        this.setRepositoryLoading("", "");
        this.renderQuestions();
      }
    }
  }

  private activateRepository(opened: RepositoryOpenResult): void {
    this.state.repository = opened;
    this.state.questions = opened.questions;
    this.state.tags = opened.tags;
    this.state.views = opened.views;
    this.state.visibleQuestions = opened.questions;
    this.state.selectedQuestionIds.clear();
    this.state.currentPaper = null;
    this.state.filters = normalizeFilters(EMPTY_FILTERS);
    this.state.searchText = "";
    this.state.selectedView = "all";
    this.state.selectedViewBaseline = normalizeFilters(EMPTY_FILTERS);
    this.state.specialViewIds = null;
    this.resetCurrentDocument("从左侧选择题目");
    this.renderRepository();
    this.renderSavedViews();
    this.writeFilterControls();
    this.renderFilterState();
    this.renderQuestions();
    this.setEnabled("search-input", true);
    for (const id of [
      "status-filter", "type-filter", "subject-filter", "chapter-filter", "year-filter",
      "language-filter", "difficulty-min-filter", "difficulty-max-filter", "topic-mode",
      "tag-filter-search", "saved-view-select", "save-view", "view-menu", "tag-manager",
      "tag-overview", "new-question", "import-questions", "paper-manager",
      "copy-repository-path",
    ]) {
      this.setEnabled(id, true);
    }
  }

  private async refreshFilteredQuestions(): Promise<void> {
    if (this.state.repository === null) return;
    const requested = normalizeFilters(this.state.filters);
    try {
      const rows = await this.bridge.request<QuestionSummary[]>(
        "question.list",
        filtersToRpc(requested),
      );
      if (!filtersEqual(requested, this.state.filters)) return;
      this.state.visibleQuestions = rows
        .map((row) => this.normalizeSearchRow(row))
        .filter((row) => this.state.specialViewIds === null || this.state.specialViewIds.has(row.id));
      this.renderFilterState();
      this.renderQuestions();
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private repositoryRevision(): string {
    const revision = this.state.current?.revision ?? this.state.repository?.revision;
    if (revision === undefined) throw new Error("题库尚未就绪");
    return revision;
  }

  private async refreshQuestionInventory(selectId?: string): Promise<void> {
    this.state.repository = await this.bridge.request<RepositoryStatus>("repository.status");
    this.state.questions = await this.bridge.request<QuestionSummary[]>("question.list", {
      offset: 0,
      limit: 20_000,
    });
    this.state.tags = await this.bridge.request<TagUsage[]>("taxonomy.list");
    this.state.views = await this.bridge.request<SavedView[]>("view.list");
    this.renderRepository();
    this.renderSavedViews();
    await this.refreshFilteredQuestions();
    if (selectId !== undefined) await this.selectQuestion(selectId);
  }

  private renderSavedViews(): void {
    const select = this.element("saved-view-select") as HTMLSelectElement;
    const labels: Record<string, string> = {
      all: "全部题目",
      draft: "草稿",
      needs_redraw: "图形待重绘",
      current_paper: "当前试卷",
    };
    select.innerHTML = "";
    for (const view of this.state.views) {
      const option = document.createElement("option");
      option.value = view.name;
      option.textContent = labels[view.name] ?? view.name;
      select.append(option);
    }
    if (![...select.options].some((option) => option.value === "all")) {
      select.prepend(new Option("全部题目", "all"));
    }
    select.value = this.state.selectedView;
    this.markViewModified();
  }

  private async selectSavedView(): Promise<void> {
    const select = this.element("saved-view-select") as HTMLSelectElement;
    const view = this.state.views.find((item) => item.name === select.value);
    this.state.selectedView = select.value || "all";
    this.state.specialViewIds = null;
    const filters = normalizeFilters(view?.filters ?? EMPTY_FILTERS);
    this.state.filters = filters;
    this.state.searchText = filters.text;
    this.state.selectedViewBaseline = normalizeFilters(filters);
    this.writeFilterControls();
    if (view !== undefined && view.kind !== "filter") {
      const rows = await this.bridge.request<QuestionSummary[]>("view.apply", { name: view.name });
      this.state.specialViewIds = new Set(rows.map((row) => row.id));
    }
    await this.refreshFilteredQuestions();
  }

  private markViewModified(): void {
    const select = this.element("saved-view-select") as HTMLSelectElement;
    const option = [...select.options].find((item) => item.value === this.state.selectedView);
    if (option === undefined) return;
    const view = this.state.views.find((item) => item.name === this.state.selectedView);
    const labels: Record<string, string> = {
      all: "全部题目",
      draft: "草稿",
      needs_redraw: "图形待重绘",
      current_paper: "当前试卷",
    };
    const base = labels[option.value] ?? view?.name ?? option.value;
    const modified = this.state.selectedViewBaseline !== null
      && !filtersEqual(this.state.filters, this.state.selectedViewBaseline);
    option.textContent = `${base}${modified ? "（已修改）" : ""}`;
  }

  private readFilterControls(): void {
    const selectValue = (id: string): string =>
      (this.element(id) as HTMLSelectElement).value;
    const numberValue = (id: string): number | null => {
      const value = selectValue(id);
      return value === "" ? null : Number(value);
    };
    this.state.filters = normalizeFilters({
      ...this.state.filters,
      text: (this.element("search-input") as HTMLInputElement).value,
      subject: selectValue("subject-filter"),
      chapter: selectValue("chapter-filter"),
      status: selectValue("status-filter"),
      type: selectValue("type-filter"),
      year: numberValue("year-filter"),
      language: selectValue("language-filter"),
      difficultyMin: numberValue("difficulty-min-filter"),
      difficultyMax: numberValue("difficulty-max-filter"),
      topicMode: selectValue("topic-mode") === "or" ? "or" : "and",
    });
    this.state.searchText = this.state.filters.text;
  }

  private writeFilterControls(): void {
    const set = (id: string, value: string | number | null): void => {
      const select = this.element(id) as HTMLSelectElement;
      const normalized = value === null ? "" : String(value);
      if (![...select.options].some((option) => option.value === normalized) && normalized) {
        select.append(new Option(`${normalized}（当前条件）`, normalized));
      }
      select.value = normalized;
    };
    (this.element("search-input") as HTMLInputElement).value = this.state.filters.text;
    set("subject-filter", this.state.filters.subject);
    set("chapter-filter", this.state.filters.chapter);
    set("status-filter", this.state.filters.status);
    set("type-filter", this.state.filters.type);
    set("year-filter", this.state.filters.year);
    set("language-filter", this.state.filters.language);
    set("difficulty-min-filter", this.state.filters.difficultyMin);
    set("difficulty-max-filter", this.state.filters.difficultyMax);
    set("topic-mode", this.state.filters.topicMode);
    this.renderFilterState();
  }

  private renderFilterState(): void {
    this.renderFacets();
    this.renderTagFilters();
    const chips = filterChips(this.state.filters);
    const host = this.element("filter-chips");
    host.innerHTML = "";
    for (const chip of chips) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "filter-chip";
      button.textContent = `${chip.label} ×`;
      button.title = `移除筛选：${chip.label}`;
      button.addEventListener("click", () => {
        this.state.filters = removeFilterChip(this.state.filters, chip);
        this.writeFilterControls();
        this.markViewModified();
        void this.refreshFilteredQuestions();
      });
      host.append(button);
    }
    this.element("active-filter-count").textContent = String(chips.length);
    this.setEnabled("clear-filters", chips.length > 0 || this.state.selectedView !== "all");
    this.markViewModified();
  }

  private renderFacets(): void {
    const definitions = [
      ["status-filter", "status"],
      ["type-filter", "type"],
      ["subject-filter", "subject"],
      ["chapter-filter", "chapter"],
      ["year-filter", "year"],
      ["language-filter", "language"],
      ["difficulty-min-filter", "difficulty"],
      ["difficulty-max-filter", "difficulty"],
    ] as const;
    for (const [id, key] of definitions) {
      const select = this.element(id) as HTMLSelectElement;
      const current = select.value || this.filterValueForFacet(key, id);
      const emptyLabel = key === "difficulty" ? "不限" : "全部";
      select.innerHTML = `<option value="">${emptyLabel}</option>`;
      const values = facetValues(this.state.questions, this.state.visibleQuestions, key);
      for (const item of values) {
        select.append(new Option(`${item.value} (${item.count})`, item.value));
      }
      if (current && !values.some((item) => item.value === current)) {
        select.append(new Option(`${current} (0)`, current));
      }
      select.value = current;
    }
  }

  private filterValueForFacet(
    key: "subject" | "chapter" | "status" | "type" | "language" | "year" | "difficulty",
    id: string,
  ): string {
    if (key === "year") return this.state.filters.year?.toString() ?? "";
    if (key === "difficulty") {
      const value = id.includes("min")
        ? this.state.filters.difficultyMin
        : this.state.filters.difficultyMax;
      return value?.toString() ?? "";
    }
    return String(this.state.filters[key] ?? "");
  }

  private renderTagFilters(): void {
    const host = this.element("tag-filter-list");
    const query = (this.element("tag-filter-search") as HTMLInputElement).value
      .trim()
      .toLocaleLowerCase("zh-CN");
    const active = new Set([
      ...this.state.filters.topics,
      ...this.state.filters.excludedTopics,
    ]);
    const visibleCounts = new Map<string, number>();
    for (const row of this.state.visibleQuestions) {
      for (const topic of new Set(row.topics)) {
        visibleCounts.set(topic, (visibleCounts.get(topic) ?? 0) + 1);
      }
    }
    const tags = [...this.state.tags]
      .filter((tag) => {
        const terms = [
          tag.slug, tag.metadata?.name_zh, tag.metadata?.name_en,
          ...(tag.metadata?.aliases ?? []),
        ].filter((value): value is string => typeof value === "string");
        return active.has(tag.slug) || !query || terms.some((value) => value.toLocaleLowerCase("zh-CN").includes(query));
      })
      .sort((left, right) => {
        const leftActive = active.has(left.slug) ? 0 : 1;
        const rightActive = active.has(right.slug) ? 0 : 1;
        return leftActive - rightActive || right.count - left.count || left.slug.localeCompare(right.slug);
      });
    host.innerHTML = "";
    for (const tag of tags) {
      const state = this.state.filters.topics.includes(tag.slug)
        ? "include"
        : this.state.filters.excludedTopics.includes(tag.slug) ? "exclude" : "neutral";
      const button = document.createElement("button");
      button.type = "button";
      button.className = `tag-filter ${state}`;
      button.dataset.state = state;
      const label = displayTag(tag);
      button.innerHTML = `<span>${escapeHtml(label)}</span><small>${visibleCounts.get(tag.slug) ?? 0}</small>`;
      button.setAttribute(
        "aria-label",
        `${label}，${state === "include" ? "包含" : state === "exclude" ? "排除" : "未选择"}；点击依次切换包含、排除、未选择`,
      );
      button.title = `${label} (${tag.slug}) · 点击循环：包含 → 排除 → 未选择`;
      button.addEventListener("click", () => {
        this.cycleTagFilter(tag.slug, state);
        this.markViewModified();
        void this.refreshFilteredQuestions();
      });
      host.append(button);
    }
    if (tags.length === 0) host.innerHTML = '<p class="muted">没有匹配标签</p>';
  }

  private cycleTagFilter(slug: string, state: "include" | "exclude" | "neutral"): void {
    this.state.filters.topics = this.state.filters.topics.filter((item) => item !== slug);
    this.state.filters.excludedTopics = this.state.filters.excludedTopics.filter((item) => item !== slug);
    if (state === "neutral") this.state.filters.topics.push(slug);
    else if (state === "include") this.state.filters.excludedTopics.push(slug);
    this.renderFilterState();
  }

  private async clearFilters(): Promise<void> {
    this.state.selectedView = "all";
    this.state.selectedViewBaseline = normalizeFilters(EMPTY_FILTERS);
    this.state.specialViewIds = null;
    this.state.filters = normalizeFilters(EMPTY_FILTERS);
    this.state.searchText = "";
    (this.element("saved-view-select") as HTMLSelectElement).value = "all";
    this.writeFilterControls();
    await this.refreshFilteredQuestions();
  }

  private async saveCurrentView(): Promise<void> {
    const current = this.state.views.find((item) => item.name === this.state.selectedView);
    const values = await this.promptTextAction({
      title: current !== undefined && !current.protected ? "更新或另存视图" : "保存当前视图",
      description: "保存搜索、字段分面、难度、年份、语言及标签条件。",
      primaryLabel: "视图名称",
      primary: current !== undefined && !current.protected ? current.name : "",
    });
    if (values === null) return;
    const result = await this.bridge.request<QuestionMutationResult>("view.save", {
      name: values.primary,
      filters: filtersToRpc(this.state.filters),
      expectedRevision: this.repositoryRevision(),
    });
    if (!result.ok) return;
    if (result.revision !== undefined) this.updateRepositoryRevision(result.revision);
    this.state.views = await this.bridge.request<SavedView[]>("view.list");
    this.state.selectedView = values.primary;
    this.state.selectedViewBaseline = normalizeFilters(this.state.filters);
    this.renderSavedViews();
    this.toast("视图已保存", "success");
  }

  private async manageCurrentView(): Promise<void> {
    const view = this.state.views.find((item) => item.name === this.state.selectedView);
    if (view === undefined) return;
    const dialog = this.element("view-action-dialog") as HTMLDialogElement;
    const kind = this.element("view-action-kind") as HTMLSelectElement;
    const name = this.element("view-action-name") as HTMLInputElement;
    this.element("view-action-description").textContent = `当前视图：${view.name}`;
    kind.innerHTML = view.protected
      ? '<option value="restore">恢复原条件</option>'
      : '<option value="update">用当前条件更新</option><option value="rename">重命名</option><option value="delete">删除</option><option value="restore">恢复原条件</option>';
    name.value = view.name;
    const updateNameState = (): void => {
      this.element("view-action-name-row").hidden = kind.value !== "rename";
    };
    kind.onchange = updateNameState;
    updateNameState();
    dialog.returnValue = "";
    dialog.showModal();
    await new Promise<void>((resolve) => dialog.addEventListener("close", () => resolve(), { once: true }));
    if (dialog.returnValue !== "confirm") return;
    if (kind.value === "restore") {
      this.state.filters = normalizeFilters(view.filters);
      this.state.selectedViewBaseline = normalizeFilters(view.filters);
      this.writeFilterControls();
      await this.refreshFilteredQuestions();
      return;
    }
    if (kind.value === "update") {
      const result = await this.bridge.request<QuestionMutationResult>("view.save", {
        name: view.name,
        filters: filtersToRpc(this.state.filters),
        expectedRevision: this.repositoryRevision(),
      });
      if (result.revision !== undefined) this.updateRepositoryRevision(result.revision);
      this.state.selectedViewBaseline = normalizeFilters(this.state.filters);
    } else if (kind.value === "rename") {
      const nextName = name.value.trim();
      if (!nextName) return;
      const result = await this.bridge.request<QuestionMutationResult>("view.rename", {
        old: view.name,
        new: nextName,
        expectedRevision: this.repositoryRevision(),
      });
      if (result.revision !== undefined) this.updateRepositoryRevision(result.revision);
      this.state.selectedView = nextName;
    } else if (kind.value === "delete") {
      const confirmed = await ask(`删除保存视图“${view.name}”？`, {
        title: "删除保存视图",
        kind: "warning",
      });
      if (!confirmed) return;
      const result = await this.bridge.request<QuestionMutationResult>("view.delete", {
        name: view.name,
        expectedRevision: this.repositoryRevision(),
      });
      if (result.revision !== undefined) this.updateRepositoryRevision(result.revision);
      this.state.selectedView = "all";
      this.state.filters = normalizeFilters(EMPTY_FILTERS);
      this.state.selectedViewBaseline = normalizeFilters(EMPTY_FILTERS);
    }
    this.state.views = await this.bridge.request<SavedView[]>("view.list");
    this.renderSavedViews();
    this.writeFilterControls();
    await this.refreshFilteredQuestions();
  }

  private async promptTextAction(options: {
    title: string;
    description: string;
    primaryLabel: string;
    primary?: string;
    secondaryLabel?: string;
    secondary?: string;
    suggestTags?: boolean;
  }): Promise<{ primary: string; secondary: string } | null> {
    const dialog = this.element("text-action-dialog") as HTMLDialogElement;
    this.element("text-action-title").textContent = options.title;
    this.element("text-action-description").textContent = options.description;
    this.element("text-action-primary-label").textContent = options.primaryLabel;
    const primary = this.element("text-action-primary") as HTMLInputElement;
    primary.value = options.primary ?? "";
    const secondaryRow = this.element("text-action-secondary-row");
    secondaryRow.hidden = options.secondaryLabel === undefined;
    this.element("text-action-secondary-label").textContent = options.secondaryLabel ?? "";
    const secondary = this.element("text-action-secondary") as HTMLInputElement;
    secondary.value = options.secondary ?? "";
    const suggestions = this.element("text-action-tag-suggestions") as HTMLDataListElement;
    const suggestionListId = suggestions.id;
    let suggestionGeneration = 0;
    const loadSuggestions = async (value: string): Promise<void> => {
      const generation = ++suggestionGeneration;
      try {
        const items = await this.bridge.request<TagUsage[]>("taxonomy.suggest", {
          text: value.trim(),
          limit: 12,
        });
        if (generation !== suggestionGeneration) return;
        suggestions.replaceChildren(...items.map((item) => {
          const option = document.createElement("option");
          option.value = item.slug;
          option.label = displayTag(item);
          return option;
        }));
      } catch {
        suggestions.replaceChildren();
      }
    };
    for (const input of [primary, secondary]) {
      input.oninput = null;
      input.removeAttribute("list");
      if (options.suggestTags) {
        input.setAttribute("list", suggestionListId);
        input.oninput = () => void loadSuggestions(input.value);
      }
    }
    suggestions.replaceChildren();
    if (options.suggestTags) void loadSuggestions(primary.value);
    dialog.returnValue = "";
    dialog.showModal();
    primary.focus();
    await new Promise<void>((resolve) => dialog.addEventListener("close", () => resolve(), { once: true }));
    suggestionGeneration += 1;
    primary.oninput = null;
    secondary.oninput = null;
    primary.removeAttribute("list");
    secondary.removeAttribute("list");
    if (dialog.returnValue !== "confirm" || !primary.value.trim()) return null;
    return { primary: primary.value.trim(), secondary: secondary.value.trim() };
  }

  private openTagManager(): void {
    this.renderTagManager();
    (this.element("tag-manager-dialog") as HTMLDialogElement).showModal();
  }

  private renderTagManager(): void {
    const host = this.element("tag-manager-list");
    const query = (this.element("tag-manager-search") as HTMLInputElement).value
      .trim()
      .toLocaleLowerCase("zh-CN");
    const tags = this.state.tags.filter((tag) => {
      const values = [
        tag.slug, tag.metadata?.name_zh, tag.metadata?.name_en,
        ...(tag.metadata?.aliases ?? []),
      ].filter((value): value is string => typeof value === "string");
      return !query || values.some((value) => value.toLocaleLowerCase("zh-CN").includes(query));
    });
    host.innerHTML = "";
    for (const tag of tags) {
      const row = document.createElement("article");
      row.className = "management-row";
      row.innerHTML = `<div><strong>${escapeHtml(displayTag(tag))}</strong><span>${escapeHtml(tag.slug)} · ${tag.count} 题 · ${escapeHtml(tag.metadata?.status ?? "未注册")}</span><small>${escapeHtml(tag.metadata?.description ?? "未填写说明")}</small></div><div class="row-actions"></div>`;
      const actions = row.querySelector<HTMLElement>(".row-actions");
      const addAction = (label: string, callback: () => void): void => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = label;
        button.addEventListener("click", callback);
        actions?.append(button);
      };
      addAction("编辑", () => void this.editTag(tag));
      addAction("重命名", () => void this.renameTag(tag.slug));
      addAction("合并", () => void this.mergeTag(tag.slug));
      addAction("删除", () => void this.deleteTag(tag.slug));
      host.append(row);
    }
    if (tags.length === 0) host.innerHTML = '<p class="muted">没有匹配标签</p>';
  }

  private async editTag(usage?: TagUsage): Promise<void> {
    const dialog = this.element("tag-editor-dialog") as HTMLDialogElement;
    const metadata = usage?.metadata;
    this.element("tag-editor-title").textContent = metadata === undefined ? "新建标签" : "编辑标签";
    const slug = this.element("tag-editor-slug") as HTMLInputElement;
    slug.value = usage?.slug ?? "";
    slug.readOnly = metadata !== undefined;
    (this.element("tag-editor-name-zh") as HTMLInputElement).value = metadata?.name_zh ?? "";
    (this.element("tag-editor-name-en") as HTMLInputElement).value = metadata?.name_en ?? "";
    (this.element("tag-editor-aliases") as HTMLInputElement).value = metadata?.aliases.join(", ") ?? "";
    (this.element("tag-editor-description") as HTMLTextAreaElement).value = metadata?.description ?? "";
    (this.element("tag-editor-status") as HTMLSelectElement).value = metadata?.status ?? "active";
    dialog.returnValue = "";
    dialog.showModal();
    await new Promise<void>((resolve) => dialog.addEventListener("close", () => resolve(), { once: true }));
    if (dialog.returnValue !== "confirm") return;
    const tag: TaxonomyTag = {
      slug: slug.value.trim(),
      name_zh: (this.element("tag-editor-name-zh") as HTMLInputElement).value.trim() || undefined,
      name_en: (this.element("tag-editor-name-en") as HTMLInputElement).value.trim() || undefined,
      aliases: (this.element("tag-editor-aliases") as HTMLInputElement).value
        .split(",").map((item) => item.trim()).filter(Boolean),
      description: (this.element("tag-editor-description") as HTMLTextAreaElement).value.trim() || undefined,
      status: (this.element("tag-editor-status") as HTMLSelectElement).value as TaxonomyTag["status"],
    };
    await this.runTaxonomyMutation("taxonomy.update", {
      tag: {
        slug: tag.slug,
        name_zh: tag.name_zh ?? null,
        name_en: tag.name_en ?? null,
        aliases: tag.aliases,
        description: tag.description ?? null,
        status: tag.status,
      },
    });
  }

  private async renameTag(slug: string): Promise<void> {
    const values = await this.promptTextAction({
      title: "重命名标签",
      description: `将 ${slug} 原子重命名，并在所有已引用题目中同步。`,
      primaryLabel: "新 slug",
    });
    if (values === null) return;
    await this.runTaxonomyMutation("taxonomy.rename", { old: slug, new: values.primary });
  }

  private async mergeTag(source: string): Promise<void> {
    const values = await this.promptTextAction({
      title: "合并标签",
      description: `将 ${source} 的全部引用合并到目标标签。`,
      primaryLabel: "目标 slug",
      suggestTags: true,
    });
    if (values === null) return;
    await this.runTaxonomyMutation("taxonomy.merge", { source, target: values.primary });
  }

  private async deleteTag(slug: string): Promise<void> {
    const confirmed = await ask(
      `删除标签“${slug}”并从所有题目移除该引用？此操作会写入统一历史。`,
      { title: "删除标签", kind: "warning" },
    );
    if (!confirmed) return;
    await this.runTaxonomyMutation("taxonomy.delete", { value: slug });
  }

  private async runTaxonomyMutation(
    method: string,
    params: Record<string, JsonValue>,
  ): Promise<void> {
    try {
      const result = await this.bridge.request<QuestionMutationResult>(method, {
        ...params,
        expectedRevision: this.repositoryRevision(),
      });
      if (!result.ok || result.revision === undefined) return;
      this.updateRepositoryRevision(result.revision);
      await this.refreshQuestionInventory();
      this.renderTagManager();
      this.toast("标签操作已提交", "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async openTagOverview(): Promise<void> {
    const overview = await this.bridge.request<TagOverview>("taxonomy.overview", { topN: 20 });
    const host = this.element("tag-overview-content");
    host.innerHTML = "";
    const section = (title: string): HTMLElement => {
      const wrapper = document.createElement("section");
      wrapper.innerHTML = `<h3>${escapeHtml(title)}</h3>`;
      host.append(wrapper);
      return wrapper;
    };
    const frequencies = section("频次");
    const frequencyGrid = document.createElement("div");
    frequencyGrid.className = "overview-frequency";
    for (const tag of overview.frequencies) {
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `<span>${escapeHtml(displayTag(tag))}</span><strong>${tag.count}</strong>`;
      button.addEventListener("click", () => this.applyOverviewTopics([tag.slug]));
      frequencyGrid.append(button);
    }
    frequencies.append(frequencyGrid);
    const pairs = section("共现");
    for (const item of overview.cooccurrences.slice(0, 20)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "overview-cell";
      button.textContent = `${item.left} + ${item.right} · ${item.count}`;
      button.addEventListener("click", () => this.applyOverviewTopics([item.left, item.right]));
      pairs.append(button);
    }
    this.renderCoverage(section("年份覆盖"), overview.year_coverage, "year");
    this.renderCoverage(section("章节覆盖"), overview.chapter_coverage, "chapter");
    (this.element("tag-overview-dialog") as HTMLDialogElement).showModal();
  }

  private renderCoverage(
    host: HTMLElement,
    cells: TagOverview["year_coverage"],
    key: "year" | "chapter",
  ): void {
    const grid = document.createElement("div");
    grid.className = "coverage-grid";
    for (const cell of cells.slice(0, 80)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "overview-cell";
      button.textContent = `${cell.axis} · ${cell.tag} · ${cell.count}`;
      button.addEventListener("click", () => {
        this.state.selectedView = "all";
        this.state.specialViewIds = null;
        this.state.filters = normalizeFilters({
          ...EMPTY_FILTERS,
          topics: [cell.tag],
          [key]: key === "year" ? Number(cell.axis) : cell.axis,
        });
        (this.element("tag-overview-dialog") as HTMLDialogElement).close();
        this.writeFilterControls();
        void this.refreshFilteredQuestions();
      });
      grid.append(button);
    }
    host.append(grid);
  }

  private applyOverviewTopics(topics: string[]): void {
    this.state.selectedView = "all";
    this.state.specialViewIds = null;
    this.state.filters = normalizeFilters({ ...EMPTY_FILTERS, topics, topicMode: "and" });
    (this.element("tag-overview-dialog") as HTMLDialogElement).close();
    this.writeFilterControls();
    void this.refreshFilteredQuestions();
  }

  private async bulkEditTags(): Promise<void> {
    if (this.state.selectedQuestionIds.size === 0) return;
    const values = await this.promptTextAction({
      title: "批量修改标签",
      description: `仅修改已明确选择的 ${this.state.selectedQuestionIds.size} 道题。`,
      primaryLabel: "添加（逗号分隔）",
      secondaryLabel: "移除（逗号分隔）",
      suggestTags: true,
    });
    if (values === null) return;
    await this.runBulkMutation("taxonomy.bulkEdit", {
      add: splitCommaValues(values.primary),
      remove: splitCommaValues(values.secondary),
    });
  }

  private async bulkUpdateField(field: "status" | "chapter"): Promise<void> {
    if (this.state.selectedQuestionIds.size === 0) return;
    const values = await this.promptTextAction({
      title: field === "status" ? "批量修改状态" : "批量修改章节",
      description: `仅修改已明确选择的 ${this.state.selectedQuestionIds.size} 道题。`,
      primaryLabel: field === "status" ? "状态" : "章节",
    });
    if (values === null) return;
    await this.runBulkMutation("question.bulkUpdate", { set: { [field]: values.primary } });
  }

  private async runBulkMutation(
    method: string,
    params: Record<string, JsonValue>,
  ): Promise<void> {
    try {
      const count = this.state.selectedQuestionIds.size;
      const result = await this.bridge.request<QuestionMutationResult>(method, {
        ...params,
        questionIds: [...this.state.selectedQuestionIds],
        expectedRevision: this.repositoryRevision(),
      });
      if (!result.ok || result.revision === undefined) return;
      this.updateRepositoryRevision(result.revision);
      await this.refreshQuestionInventory();
      this.toast(`已更新 ${count} 道题`, "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private updateRepositoryRevision(revision: string): void {
    if (this.state.repository !== null) this.state.repository.revision = revision;
    if (this.state.current !== null) this.state.current.revision = revision;
    if (this.state.currentPaper !== null) this.state.currentPaper.revision = revision;
  }

  private async promptQuestionDetails(
    title: string,
    defaults: { id?: string; name?: string; idPattern?: boolean; nameVisible?: boolean } = {},
  ): Promise<{ id: string; name: string } | null> {
    const dialog = this.element("question-dialog") as HTMLDialogElement;
    const id = this.element("question-dialog-id") as HTMLInputElement;
    const name = this.element("question-dialog-name") as HTMLInputElement;
    this.element("question-dialog-title").textContent = title;
    id.value = defaults.id ?? "";
    name.value = defaults.name ?? "";
    id.pattern = defaults.idPattern === false ? ".+" : "[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+";
    this.element("question-dialog-title-row").hidden = defaults.nameVisible === false;
    dialog.returnValue = "";
    dialog.showModal();
    await new Promise<void>((resolve) => dialog.addEventListener("close", () => resolve(), { once: true }));
    if (dialog.returnValue !== "confirm" || !id.value.trim() || (!this.element("question-dialog-title-row").hidden && !name.value.trim())) {
      return null;
    }
    return { id: id.value.trim(), name: name.value.trim() };
  }

  private async createQuestion(): Promise<void> {
    const values = await this.promptQuestionDetails("新建题目");
    if (values === null) return;
    try {
      const result = await this.bridge.request<QuestionMutationResult>("question.create", {
        id: values.id,
        title: values.name,
        expectedRevision: this.repositoryRevision(),
      });
      await this.refreshQuestionInventory(values.id);
      this.toast(`已新建 ${values.id}`, "success");
      if (!result.ok) this.toast("新建题目未通过校验", "error");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async copyQuestion(): Promise<void> {
    const sourceId = this.state.current?.question.id;
    if (typeof sourceId !== "string") return;
    const values = await this.promptQuestionDetails("复制题目", { nameVisible: false });
    if (values === null) return;
    try {
      await this.bridge.request<QuestionMutationResult>("question.copy", {
        sourceId,
        newId: values.id,
        expectedRevision: this.repositoryRevision(),
      });
      await this.refreshQuestionInventory(values.id);
      this.toast(`已复制为 ${values.id}`, "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async importQuestions(): Promise<void> {
    const selected = await open({
      multiple: false,
      directory: false,
      title: "导入 qbank JSON 或 JSONL",
      filters: [{ name: "qbank exchange", extensions: ["json", "jsonl"] }],
    });
    if (typeof selected !== "string") return;
    try {
      const result = await this.bridge.request<QuestionMutationResult>("question.import", {
        path: selected,
        expectedRevision: this.repositoryRevision(),
      });
      if (!result.ok) throw new Error("导入 dry-run 未通过，题库未写入");
      await this.refreshQuestionInventory();
      this.toast("导入完成并已刷新题目列表", "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async deleteQuestion(): Promise<void> {
    const questionId = this.state.current?.question.id;
    if (typeof questionId !== "string") return;
    const confirmed = await ask(`确定删除题目 ${questionId}？资产不会被自动删除。`, {
      title: "删除题目",
      kind: "warning",
      okLabel: "删除",
      cancelLabel: "取消",
    });
    if (!confirmed) return;
    try {
      await this.bridge.request<QuestionMutationResult>("question.delete", {
        id: questionId,
        expectedRevision: this.repositoryRevision(),
      });
      this.state.current = null;
      this.buffer.load("");
      this.editor?.destroy();
      this.element("editor-frame").classList.add("empty");
      await this.refreshQuestionInventory();
      this.toast(`已删除 ${questionId}`, "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private updateQuestionActions(): void {
    const hasCurrent = this.state.current !== null;
    this.setEnabled("copy-question", hasCurrent);
    this.setEnabled("delete-question", hasCurrent);
    const hasSelection = this.state.selectedQuestionIds.size > 0;
    for (const id of ["paper-create", "paper-add"]) this.setEnabled(id, hasSelection);
    const batch = this.element("batch-bar");
    batch.hidden = !hasSelection;
    this.element("batch-summary").textContent = `已选择 ${this.state.selectedQuestionIds.size} 道题`;
    for (const id of ["batch-tag", "batch-status", "batch-chapter", "batch-paper"]) {
      this.setEnabled(id, hasSelection);
    }
  }

  private async saveMetadata(): Promise<void> {
    const current = this.state.current;
    if (current === null) return;
    if (this.buffer.snapshot().dirty) {
      this.toast("请先保存正文，再应用结构化属性。", "warning");
      return;
    }
    const form = this.element("metadata-form") as HTMLFormElement;
    const values = new FormData(form);
    const topics = String(values.get("topics") ?? "").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
    const reference = String(values.get("sourceReference") ?? "").trim();
    try {
      const result = await this.bridge.request<QuestionMutationResult>("question.update", {
        id: String(current.question.id),
        set: {
          title: String(values.get("title") ?? ""),
          subject: String(values.get("subject") ?? ""),
          chapter: String(values.get("chapter") ?? "") || null,
          type: String(values.get("type") ?? ""),
          status: String(values.get("status") ?? ""),
          difficulty: Number(values.get("difficulty") ?? 1),
          source: { type: String(values.get("sourceType") ?? "manual"), reference: reference || null },
        },
        topics,
        expectedRevision: current.revision,
      });
      if (!result.ok || result.source === undefined || result.question === undefined || result.revision === undefined) {
        throw new Error("属性更新未通过 qbank 校验");
      }
      this.state.current = { question: result.question, source: result.source, revision: result.revision, diagnostics: [] };
      this.buffer.markSaved(result.source);
      await this.refreshInspector(String(current.question.id), true);
      await this.refreshQuestionInventory();
      this.toast("题目属性已保存", "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async openPaperManager(): Promise<void> {
    try {
      this.state.papers = await this.bridge.request<PaperSummary[]>("paper.list");
      const select = this.element("paper-select") as HTMLSelectElement;
      select.innerHTML = '<option value="">选择试卷…</option>' + this.state.papers.map((paper) => `<option value="${escapeHtml(paper.path)}">${escapeHtml(paper.title)}</option>`).join("");
      this.renderPaperSummary();
      (this.element("paper-dialog") as HTMLDialogElement).showModal();
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async selectPaper(): Promise<void> {
    const path = (this.element("paper-select") as HTMLSelectElement).value;
    if (!path) {
      this.state.currentPaper = null;
      this.renderPaperSummary();
      return;
    }
    this.state.currentPaper = await this.bridge.request<PaperDocument>("paper.get", { path });
    this.renderPaperSummary();
  }

  private renderPaperSummary(): void {
    const host = this.element("paper-summary");
    const paperDocument = this.state.currentPaper;
    if (paperDocument === null) {
      host.innerHTML = '<p class="muted">选择现有试卷，或用已勾选题目新建试卷。</p>';
      return;
    }
    host.innerHTML = "";
    const sections = Array.isArray(paperDocument.paper.sections) ? paperDocument.paper.sections : [];
    sections.forEach((rawSection, sectionIndex) => {
      if (rawSection === null || typeof rawSection !== "object" || Array.isArray(rawSection)) return;
      const section = rawSection as Record<string, JsonValue>;
      const sectionElement = document.createElement("section");
      sectionElement.className = "paper-section-editor";
      sectionElement.innerHTML = `<h3>${escapeHtml(String(section.title ?? `第 ${sectionIndex + 1} 节`))}</h3>`;
      const questions = Array.isArray(section.questions) ? section.questions : [];
      questions.forEach((rawQuestion, questionIndex) => {
        if (rawQuestion === null || typeof rawQuestion !== "object" || Array.isArray(rawQuestion)) return;
        const question = rawQuestion as Record<string, JsonValue>;
        const row = document.createElement("div");
        row.className = "paper-question-row";
        row.innerHTML = `<span>${escapeHtml(String(question.id))}</span><label>分值 <input type="number" min="0.1" step="0.5" value="${escapeHtml(String(question.score))}" /></label><button type="button" aria-label="上移">↑</button><button type="button" aria-label="下移">↓</button>`;
        row.querySelector("input")?.addEventListener("change", (event) => {
          question.score = Number((event.target as HTMLInputElement).value);
        });
        const buttons = row.querySelectorAll("button");
        buttons[0]?.addEventListener("click", () => {
          if (questionIndex > 0) [questions[questionIndex - 1], questions[questionIndex]] = [questions[questionIndex], questions[questionIndex - 1]];
          this.renderPaperSummary();
        });
        buttons[1]?.addEventListener("click", () => {
          if (questionIndex + 1 < questions.length) [questions[questionIndex + 1], questions[questionIndex]] = [questions[questionIndex], questions[questionIndex + 1]];
          this.renderPaperSummary();
        });
        sectionElement.append(row);
      });
      host.append(sectionElement);
    });
  }

  private async createPaper(): Promise<void> {
    const selected = [...this.state.selectedQuestionIds];
    if (selected.length === 0) return;
    const values = await this.promptQuestionDetails("新建试卷", {
      id: "generated/studio-paper.yaml",
      name: "新试卷",
      idPattern: false,
    });
    if (values === null) return;
    try {
      await this.bridge.request("paper.create", {
        path: values.id,
        title: values.name,
        questionIds: selected,
        expectedRevision: this.repositoryRevision(),
      });
      this.state.papers = await this.bridge.request<PaperSummary[]>("paper.list");
      const created = this.state.papers.find((paper) => paper.path.endsWith(values.id.replaceAll("\\", "/")) || paper.title === values.name);
      if (created !== undefined) {
        (this.element("paper-select") as HTMLSelectElement).value = created.path;
        this.state.currentPaper = await this.bridge.request<PaperDocument>("paper.get", { path: created.path });
      }
      this.renderPaperSummary();
      this.toast("试卷已创建", "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async addSelectedToPaper(): Promise<void> {
    const paper = this.state.currentPaper;
    const selected = [...this.state.selectedQuestionIds];
    if (paper === null || selected.length === 0) return;
    await this.bridge.request("paper.addQuestions", {
      path: paper.path,
      questionIds: selected,
      expectedRevision: paper.revision,
    });
    this.state.currentPaper = await this.bridge.request<PaperDocument>("paper.get", { path: paper.path });
    this.renderPaperSummary();
    this.toast("所选题目已加入试卷", "success");
  }

  private async savePaper(): Promise<void> {
    const paper = this.state.currentPaper;
    if (paper === null) return;
    const result = await this.bridge.request<{ revision: string; paper: Record<string, JsonValue> }>("paper.save", {
      path: paper.path,
      paper: paper.paper,
      expectedRevision: paper.revision,
    });
    this.state.currentPaper = { ...paper, paper: result.paper, revision: result.revision };
    this.toast("试卷顺序与分值已保存", "success");
  }

  private async validatePaper(): Promise<void> {
    const paper = this.state.currentPaper;
    if (paper === null) return;
    const report = await this.bridge.request<PaperValidationResult>("paper.validate", { path: paper.path });
    const host = this.element("paper-diagnostics");
    host.textContent = report.ok ? "试卷校验通过" : report.issues.map((item) => `${item.code}: ${item.message}`).join("\n");
    host.className = `paper-diagnostics ${report.ok ? "success" : "error"}`;
  }

  private async exportPaper(withSolutions: boolean): Promise<void> {
    const paper = this.state.currentPaper;
    if (paper === null) return;
    const output = await chooseSavePath({
      title: withSolutions ? "导出答案版试卷" : "导出学生版试卷",
      defaultPath: `${paper.path.split("/").at(-1)?.replace(/\.ya?ml$/i, "") ?? "paper"}-${withSolutions ? "solutions" : "student"}.html`,
      filters: [{ name: "HTML", extensions: ["html"] }],
    });
    if (typeof output !== "string") return;
    await this.bridge.request("paper.build", {
      path: paper.path,
      format: "html",
      output,
      options: {
        with_answers: withSolutions,
        with_solutions: withSolutions,
        with_rubric: withSolutions,
        show_ids: false,
      },
      expectedRevision: paper.revision,
    });
    this.toast(`已导出${withSolutions ? "答案版" : "学生版"}试卷`, "success");
  }

  private normalizeSearchRow(row: QuestionSummary): QuestionSummary {
    const known = this.state.questions.find((item) => item.id === row.id);
    return known ?? row;
  }

  private async selectQuestion(questionId: string): Promise<void> {
    if (this.state.current?.question.id === questionId && !this.state.loading) return;
    if (!(await this.resolveDirtyState("切换题目"))) return;
    this.resetCurrentDocument("");
    const loading = this.buffer.snapshot();
    const generation = loading.generation;
    this.setLoading(true, `正在加载 ${questionId}…`);
    this.element("document-title").textContent = questionId;
    this.element("document-identity").textContent = "正在读取权威 Markdown 与资产…";
    this.renderInspectorLoading();
    this.preview?.loading(`正在加载 ${questionId}…`, this.state.theme);
    try {
      const [document, assets, history] = await Promise.all([
        this.bridge.request<QuestionDocument>("question.get", { id: questionId }),
        this.bridge.request<AssetItem[]>("asset.list", { questionId }),
        this.bridge.request<HistoryEntry[]>("history.list", { questionId }),
      ]);
      if (!this.buffer.isCurrent(generation)) return;
      this.state.current = document;
      this.state.assets = assets;
      this.state.history = history;
      this.state.validation = null;
      this.updatePreviewBindings(assets);
      this.buffer.markSaved(document.source);
      this.renderCurrentDocument();
    } catch (error) {
      if (this.buffer.isCurrent(generation)) {
        const message = error instanceof Error ? error.message : String(error);
        this.renderQuestionLoadError(questionId, message);
        this.toast(message, "error");
      }
    } finally {
      if (this.buffer.isCurrent(generation)) this.setLoading(false);
    }
  }

  private resetCurrentDocument(emptyMessage: string): void {
    this.state.current = null;
    this.state.assets = [];
    this.state.history = [];
    this.state.validation = null;
    this.previewBindings.clear();
    this.previewGeneration += 1;
    if (this.previewTimer !== 0) window.clearTimeout(this.previewTimer);
    this.previewTimer = 0;
    this.editorGeneration += 1;
    this.editor?.destroy();
    this.editor = null;
    this.editorReady = false;
    this.element("vditor").innerHTML = "";
    this.buffer.load("");
    this.element("editor-frame").classList.add("empty");
    this.element("editor-empty").hidden = false;
    this.element("editor-empty").textContent = emptyMessage;
    this.element("document-title").textContent = "选择一道题目";
    this.element("document-identity").textContent = "源码是权威缓冲区，预览不会改写 Markdown。";
    this.element("inspector-id").textContent = "—";
    this.element("metadata-form").innerHTML = '<p class="muted">未加载</p>';
    this.element("asset-list").innerHTML = '<p class="muted">未加载</p>';
    this.element("history-list").innerHTML = '<p class="muted">未加载</p>';
    this.element("validation-badge").textContent = "尚未校验";
    this.element("validation-badge").className = "validation-badge neutral";
    this.element("diagnostic-bar").hidden = true;
    this.element("diagnostic-bar").innerHTML = "";
    this.preview?.clear(this.state.theme);
    this.updateDirty(false);
  }

  private renderInspectorLoading(): void {
    this.element("inspector-id").textContent = "读取中";
    this.element("metadata-form").innerHTML = '<p class="muted">正在读取题目属性…</p>';
    this.element("asset-list").innerHTML = '<p class="muted">正在检查资源边界…</p>';
    this.element("history-list").innerHTML = '<p class="muted">正在读取历史…</p>';
  }

  private renderQuestionLoadError(questionId: string, message: string): void {
    this.state.current = null;
    this.element("editor-frame").classList.add("empty");
    this.element("editor-empty").hidden = false;
    this.element("editor-empty").textContent = `无法读取 ${questionId}`;
    this.element("document-title").textContent = questionId;
    this.element("document-identity").textContent = message;
    this.element("inspector-id").textContent = "错误";
    this.element("metadata-form").innerHTML =
      `<p class="inline-error">${escapeHtml(message)}</p>`;
    this.element("asset-list").innerHTML = '<p class="muted">题目未加载，未读取资源。</p>';
    this.element("history-list").innerHTML = '<p class="muted">题目未加载。</p>';
    this.preview?.error(message, this.state.theme);
  }

  private createEditor(source: string): void {
    this.editor?.destroy();
    this.editorReady = false;
    const generation = ++this.editorGeneration;
    const host = this.element("vditor");
    host.innerHTML = "";
    this.element("editor-frame").dataset.mode = this.state.mode;
    const mode = "sv";
    let instance: Vditor | null = null;
    instance = new Vditor(host, {
      value: source,
      mode,
      height: "100%",
      minHeight: 320,
      lang: "zh_CN",
      theme: this.state.theme === "dark" ? "dark" : "classic",
      cdn: `${window.location.origin}/vendor/vditor`,
      cache: { enable: false },
      toolbar: [],
      tab: "  ",
      undoDelay: 150,
      preview: {
        delay: 80,
        mode: "editor",
        maxWidth: 960,
        math: {
          engine: "MathJax",
          inlineDigit: true,
          macros: {
            ...COMMON_MATH_MACROS,
            ...(this.state.repository?.mathMacros ?? {}),
          },
        },
        markdown: { sanitize: true, autoSpace: false, fixTermTypo: false },
        transform: (html) => this.rewritePreviewHtml(html),
      },
      input: (value) => {
        if (this.editorReady) {
          this.applyEditorProjection(value);
          this.scheduleSecurePreview();
        }
      },
      after: () => {
        if (generation !== this.editorGeneration || instance === null) return;
        this.editor = instance;
        instance.setPreviewMode("editor");
        instance.setValue(source, true);
        this.editorProjection = instance.getValue();
        this.projectionSources = new Map([[this.editorProjection, this.buffer.snapshot().source]]);
        this.editorReady = true;
        if (this.state.mode !== "instant") instance.focus();
        void this.renderSecurePreview();
      },
    });
    this.editor = instance;
  }

  private applyEditorProjection(nextProjection: string): void {
    if (nextProjection === this.editorProjection) return;
    const current = this.buffer.snapshot().source;
    this.rememberProjection(this.editorProjection, current);
    const knownSource = this.projectionSources.get(nextProjection);
    if (knownSource !== undefined) {
      this.editorProjection = nextProjection;
      const snapshot = this.buffer.edit(knownSource);
      this.updateDirty(snapshot.dirty);
      return;
    }
    const authoritativeProjection = this.state.mode === "instant" ? bodyForPreview(current) : current;
    const patches = this.projectionPatcher.patch_make(this.editorProjection, nextProjection);
    const [merged, applied] = this.projectionPatcher.patch_apply(patches, authoritativeProjection);
    if (!applied.every(Boolean)) {
      this.toast("无法将编辑差异安全映射回原始 Markdown；已保留权威内容。", "error", 0);
      this.createEditor(this.state.mode === "instant" ? bodyForPreview(current) : current);
      return;
    }
    const source = this.state.mode === "instant" ? this.restoreFrontmatter(merged) : merged;
    this.editorProjection = nextProjection;
    this.rememberProjection(nextProjection, source);
    const snapshot = this.buffer.edit(source);
    this.updateDirty(snapshot.dirty);
  }

  private rememberProjection(projection: string, source: string): void {
    this.projectionSources.delete(projection);
    this.projectionSources.set(projection, source);
    while (this.projectionSources.size > 64) {
      const oldest = this.projectionSources.keys().next().value as string | undefined;
      if (oldest === undefined) break;
      this.projectionSources.delete(oldest);
    }
  }

  private rewritePreviewHtml(html: string): string {
    const value = rewriteBackslashMathHtml(html, this.buffer.snapshot().source);
    if (this.previewBindings.size === 0) return value;
    const parsed = new DOMParser().parseFromString(value, "text/html");
    for (const image of parsed.body.querySelectorAll<HTMLImageElement>("img[src]")) {
      const source = image.getAttribute("src");
      if (source === null) continue;
      const binding = this.previewBindings.get(source);
      if (binding !== undefined) image.setAttribute("src", binding);
    }
    return parsed.body.innerHTML;
  }

  private async renderSecurePreview(): Promise<void> {
    if (this.previewTimer !== 0) window.clearTimeout(this.previewTimer);
    this.previewTimer = 0;
    const preview = this.preview;
    if (preview === null || this.state.current === null) return;
    const generation = ++this.previewGeneration;
    const source = guardMathSource(bodyForPreview(this.buffer.snapshot().source));
    const formulaCount = (source.match(/\$\$|\\\[|\\\(|(?<!\$)\$(?!\$)/g) ?? []).length;
    const progress = this.element("preview-progress");
    preview.element.ariaBusy = "true";
    progress.hidden = true;
    const progressLabel = progress.querySelector("span:last-child");
    if (progressLabel !== null) {
      progressLabel.textContent = `正在渐进渲染 ${formulaCount} 个公式…`;
    }
    const progressDelay = window.setTimeout(() => {
      if (generation === this.previewGeneration) progress.hidden = false;
    }, 140);
    try {
      const html = await Vditor.md2html(source, {
        cdn: `${window.location.origin}/vendor/vditor`,
        lang: "zh_CN",
        mode: this.state.theme,
        math: {
          engine: "MathJax",
          inlineDigit: true,
          macros: {
            ...COMMON_MATH_MACROS,
            ...(this.state.repository?.mathMacros ?? {}),
          },
        },
        markdown: { sanitize: true, autoSpace: false, fixTermTypo: false },
        transform: (value) => this.rewritePreviewHtml(value),
      });
      const rendered = await this.renderMathHtml(this.rewritePreviewHtml(html));
      if (generation !== this.previewGeneration) return;
      preview.render(rendered, this.state.theme);
    } catch (error) {
      if (generation !== this.previewGeneration) return;
      const message = error instanceof Error ? error.message : String(error);
      preview.render(`<p class="preview-error">预览失败：${escapeHtml(message)}</p>`, this.state.theme);
    } finally {
      window.clearTimeout(progressDelay);
      if (generation === this.previewGeneration) {
        progress.hidden = true;
        preview.element.ariaBusy = "false";
      }
    }
  }

  private scheduleSecurePreview(): void {
    if (this.previewTimer !== 0) window.clearTimeout(this.previewTimer);
    this.previewTimer = window.setTimeout(() => {
      this.previewTimer = 0;
      void this.renderSecurePreview();
    }, 80);
  }

  private async renderMathHtml(html: string): Promise<string> {
    const worker = document.createElement("div");
    worker.className = "secure-preview-render-worker";
    worker.inert = true;
    worker.ariaHidden = "true";
    worker.innerHTML = sanitizePreviewHtml(html);
    document.body.append(worker);
    try {
      Vditor.mathRender(worker, {
        cdn: `${window.location.origin}/vendor/vditor`,
        math: {
          engine: "MathJax",
          inlineDigit: true,
          macros: {
            ...COMMON_MATH_MACROS,
            ...(this.state.repository?.mathMacros ?? {}),
          },
        },
      });
      const deadline = performance.now() + 4_000;
      while (worker.querySelector(".language-math") !== null && performance.now() < deadline) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 25));
      }
      return sanitizePreviewHtml(worker.innerHTML);
    } finally {
      worker.remove();
    }
  }

  private restoreFrontmatter(body: string): string {
    const current = this.buffer.snapshot().source;
    const match = /^---\r?\n[\s\S]*?\r?\n---\r?\n/.exec(current);
    return `${match?.[0] ?? ""}${bodyForPreview(body)}`;
  }

  private setMode(mode: EditorMode): void {
    if (this.state.mode === mode) return;
    const source = this.buffer.snapshot().source;
    this.state.mode = mode;
    this.element("editor-frame").dataset.mode = mode;
    for (const button of this.root.querySelectorAll<HTMLButtonElement>(".mode-button")) {
      button.classList.toggle("active", button.dataset.mode === mode);
    }
    if (this.state.current !== null) this.createEditor(source);
  }

  private async validate(): Promise<ValidationResult | null> {
    const current = this.state.current;
    if (current === null) return null;
    const snapshot = this.buffer.snapshot();
    const generation = snapshot.generation;
    this.element("validation-badge").textContent = "校验中…";
    try {
      const result = await this.bridge.request<ValidationResult>("question.validate", {
        id: current.question.id as string,
        source: snapshot.source,
      });
      if (!this.buffer.isCurrent(generation)) return null;
      this.state.validation = result;
      this.renderValidation(result);
      return result;
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
      return null;
    }
  }

  private async save(): Promise<boolean> {
    const current = this.state.current;
    const snapshot = this.buffer.snapshot();
    if (current === null) return false;
    if (!snapshot.dirty) return true;
    const validation = await this.validate();
    if (validation === null || !validation.ok) return false;
    this.setEnabled("save", false);
    try {
      const result = await this.bridge.request<SaveResult>("question.save", {
        id: current.question.id as string,
        source: snapshot.source,
        expectedRevision: current.revision,
      });
      if (!result.ok) {
        this.renderValidation(result);
        return false;
      }
      this.buffer.markSaved(result.source);
      current.source = result.source;
      current.revision = result.revision;
      if (result.source !== snapshot.source) this.createEditor(result.source);
      this.updateDirty(false);
      this.toast(result.indexUpdated ? "题目已保存" : "题目已保存；索引需要重建", result.indexUpdated ? "success" : "warning");
      await this.refreshInspector(current.question.id as string);
      return true;
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
      return false;
    } finally {
      this.updateDirty(this.buffer.snapshot().dirty);
    }
  }

  private async resolveDirtyState(action: string): Promise<boolean> {
    if (!this.buffer.snapshot().dirty) return true;
    const dialog = this.element("dirty-state-dialog") as HTMLDialogElement;
    this.element("dirty-state-description").textContent =
      `${action}前需要处理当前题目的未保存修改。`;
    dialog.returnValue = "cancel";
    dialog.showModal();
    const choice = await new Promise<string>((resolve) => {
      dialog.addEventListener("close", () => resolve(dialog.returnValue), { once: true });
    });
    if (choice === "save") return this.save();
    if (choice !== "discard") return false;
    const questionId = this.state.current?.question.id;
    if (typeof questionId !== "string") return false;
    return this.reloadCurrentQuestion(questionId, true);
  }

  private async refreshInspector(questionId: string, refreshPreview = false): Promise<void> {
    await this.reloadCurrentQuestion(questionId, false, refreshPreview);
  }

  private async reloadCurrentQuestion(
    questionId: string,
    resetSource: boolean,
    refreshPreview = true,
  ): Promise<boolean> {
    try {
      const [document, assets, history] = await Promise.all([
        this.bridge.request<QuestionDocument>("question.get", { id: questionId }),
        this.bridge.request<AssetItem[]>("asset.list", { questionId }),
        this.bridge.request<HistoryEntry[]>("history.list", { questionId }),
      ]);
      if (this.state.current?.question.id !== questionId) return false;
      if (resetSource) {
        this.state.current = document;
        this.buffer.markSaved(document.source);
      } else {
        this.state.current.question = document.question;
        this.state.current.revision = document.revision;
      }
      this.state.assets = assets;
      this.state.history = history;
      this.updatePreviewBindings(assets);
      this.renderInspector();
      if (resetSource || refreshPreview) {
        const source = this.buffer.snapshot().source;
        this.createEditor(this.state.mode === "instant" ? bodyForPreview(source) : source);
      }
      if (resetSource) this.updateDirty(false);
      return true;
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
      return false;
    }
  }

  private updatePreviewBindings(assets: AssetItem[]): void {
    this.previewBindings = new Map();
    for (const item of assets) {
      if (item.previewDataUrl === null) continue;
      this.previewBindings.set(item.reference, item.previewDataUrl);
      if (item.kind === "logical") {
        this.previewBindings.set(`qbank-asset:${item.assetId}`, item.previewDataUrl);
        this.previewBindings.set(`asset:${item.assetId}`, item.previewDataUrl);
      }
    }
  }

  private async handlePaste(event: ClipboardEvent): Promise<void> {
    const file = [...(event.clipboardData?.files ?? [])].find((item) => item.type.startsWith("image/"));
    if (file === undefined) return;
    event.preventDefault();
    await this.createAsset(file);
  }

  private async handleDrop(event: DragEvent): Promise<void> {
    this.element("editor-frame").classList.remove("drag-active");
    const file = [...(event.dataTransfer?.files ?? [])].find((item) => item.type.startsWith("image/"));
    if (file === undefined) return;
    event.preventDefault();
    await this.createAsset(file);
  }

  private async createAsset(file: File): Promise<void> {
    if (!(await this.resolveDirtyState("创建图形资产"))) return;
    const current = this.state.current;
    if (current === null) return;
    const snapshot = this.buffer.snapshot();
    const ids = this.state.assets.map((item) => item.assetId);
    const assetId = nextAssetId(ids);
    const source = insertAssetReference(snapshot.source, assetId);
    const dataBase64 = await fileBase64(file);
    try {
      const result = await this.bridge.request<{ ok: boolean; revision: string }>("asset.create", {
        questionId: current.question.id as string,
        assetId,
        source,
        mediaType: file.type || "image/png",
        dataBase64,
        expectedRevision: current.revision,
      });
      if (!result.ok) throw new Error("资产创建未通过校验");
      await this.reloadCurrentQuestion(current.question.id as string, true);
      this.toast(`已创建图形资产 ${assetId}`, "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async assetAction(asset: AssetItem, action: string): Promise<void> {
    if (!(await this.resolveDirtyState("执行资源操作"))) return;
    const current = this.state.current;
    const questionId = current?.question.id;
    if (current === null || typeof questionId !== "string") return;
    const expectedRevision = current.revision;
    const assetId = asset.assetId;
    try {
      if (action === "replace") {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*,.ipe,.pdf";
        input.addEventListener("change", () => {
          const file = input.files?.[0];
          if (file !== undefined) void this.replaceAsset(questionId, assetId, file);
        });
        input.click();
        return;
      }
      if (action === "replace_clipboard") {
        await this.replaceAssetFromClipboard(questionId, assetId);
        return;
      }
      if (action === "render") {
        await this.bridge.request("asset.render", {
          questionId,
          assetId,
          formats: ["svg", "png", "pdf"],
          expectedRevision,
        });
      } else if (action === "reconcile") {
        await this.bridge.request("asset.reconcile", {
          questionId,
          assetId,
          expectedRevision,
        });
      } else {
        await this.bridge.request("asset.open", {
          questionId,
          assetId,
          action,
          reference: asset.kind === "logical" ? "" : asset.reference,
          expectedRevision,
        });
      }
      if (action === "render" || action === "reconcile") {
        await this.reloadCurrentQuestion(questionId, true);
      }
      this.toast("资产操作已完成", "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async replaceAsset(questionId: string, assetId: string, file: File): Promise<void> {
    const current = this.state.current;
    if (current === null || current.question.id !== questionId) return;
    try {
      await this.bridge.request("asset.replace", {
        questionId,
        assetId,
        mediaType: file.type || "image/png",
        dataBase64: await fileBase64(file),
        expectedRevision: current.revision,
      });
      await this.reloadCurrentQuestion(questionId, true);
      this.toast("已添加新的资源版本", "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private async replaceAssetFromClipboard(questionId: string, assetId: string): Promise<void> {
    if (navigator.clipboard?.read === undefined) {
      throw new Error("当前 WebView 不支持读取剪贴板图片");
    }
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const mediaType = item.types.find((type) => type.startsWith("image/"));
      if (mediaType === undefined) continue;
      const blob = await item.getType(mediaType);
      const extension = mediaType.split("/")[1]?.replace("jpeg", "jpg") ?? "png";
      await this.replaceAsset(
        questionId,
        assetId,
        new File([blob], `clipboard.${extension}`, { type: mediaType }),
      );
      return;
    }
    throw new Error("剪贴板中没有可用图片");
  }

  private showFormulaMenu(event: MouseEvent): void {
    if (!(event.target instanceof Element)) return;
    const formula = event.target.closest<HTMLElement>("[data-math]");
    const tex = formula?.dataset.math;
    if (formula === null || tex === undefined) return;
    event.preventDefault();
    event.stopPropagation();
    this.openFormulaMenu(event.clientX, event.clientY, formula, tex);
  }

  private showFormulaMenuFromPreview(event: MouseEvent, formula: HTMLElement): void {
    const tex = formula.dataset.math;
    if (tex === undefined) return;
    const bounds = this.preview?.element.getBoundingClientRect();
    this.openFormulaMenu(
      event.clientX + (bounds?.left ?? 0),
      event.clientY + (bounds?.top ?? 0),
      formula,
      tex,
    );
  }

  private openFormulaMenu(clientX: number, clientY: number, formula: HTMLElement, tex: string): void {
    this.root.querySelector(".formula-menu")?.remove();
    const menu = document.createElement("div");
    menu.className = "formula-menu";
    menu.style.left = `${Math.min(clientX, window.innerWidth - 190)}px`;
    menu.style.top = `${Math.min(clientY, window.innerHeight - 92)}px`;
    const delimited = formula.tagName === "DIV" || formula.classList.contains("qbank-display-math")
      ? `$$\n${tex}\n$$`
      : `\\(${tex}\\)`;
    for (const [label, value] of [["复制公式", delimited], ["复制原始 TeX", tex]] as const) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", () => {
        void this.copyText(value, label);
        menu.remove();
      });
      menu.append(button);
    }
    this.root.append(menu);
  }

  private async copyText(value: string, label: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(value);
      this.toast(`${label}已写入剪贴板`, "success");
    } catch (error) {
      this.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  private renderRepository(): void {
    const repository = this.state.repository;
    if (repository === null) return;
    this.element("repository-name").textContent = repository.name;
    this.element("repository-path").textContent = "点击复制完整路径";
    this.element("copy-repository-path").title = `复制题库路径：${repository.root}`;
    const health = this.element("repository-health");
    health.textContent = repository.healthy ? "健康 · 索引正常" : repository.indexDirty ? "索引待恢复" : "需要检查";
    health.className = `health ${repository.healthy ? "success" : "warning"}`;
  }

  private renderQuestions(): void {
    const list = this.element("question-list");
    list.innerHTML = "";
    for (const question of this.state.visibleQuestions) {
      const shell = document.createElement("div");
      shell.className = "question-row-shell";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "question-selector";
      checkbox.checked = this.state.selectedQuestionIds.has(question.id);
      checkbox.setAttribute("aria-label", `选择 ${question.title}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) this.state.selectedQuestionIds.add(question.id);
        else this.state.selectedQuestionIds.delete(question.id);
        this.updateQuestionActions();
      });
      const row = document.createElement("button");
      row.className = "question-row";
      row.type = "button";
      row.role = "option";
      row.dataset.questionId = question.id;
      row.ariaSelected = String(this.state.current?.question.id === question.id);
      row.innerHTML = `<span class="question-title">${escapeHtml(question.title)}</span><span class="question-meta">${escapeHtml(question.id)} · ${escapeHtml(question.subject)}</span><span class="status-dot ${escapeHtml(question.status)}" title="${escapeHtml(question.status)}"></span>`;
      row.addEventListener("click", () => void this.selectQuestion(question.id));
      shell.append(checkbox, row);
      list.append(shell);
    }
    if (this.state.visibleQuestions.length === 0) list.innerHTML = '<div class="empty-state">没有匹配的题目</div>';
    const currentId = this.state.current?.question.id;
    const currentOutside = typeof currentId === "string"
      && !this.state.visibleQuestions.some((question) => question.id === currentId);
    this.element("result-count").textContent = currentOutside
      ? `${this.state.visibleQuestions.length} 题 · 当前题目不在筛选结果中`
      : `${this.state.visibleQuestions.length} 题`;
    this.updateQuestionActions();
  }

  private renderCurrentDocument(): void {
    const current = this.state.current;
    if (current === null) return;
    this.element("editor-frame").classList.remove("empty");
    this.element("editor-empty").hidden = true;
    const question = current.question;
    this.element("document-title").textContent = String(question.title);
    this.element("document-identity").textContent = `${String(question.id)} · ${String(question.subject)} · ${String(question.status)}`;
    this.createEditor(current.source);
    this.updateDirty(false);
    this.renderInspector();
    this.renderValidation({ ok: true, diagnostics: [], canonicalChanged: false });
  }

  private renderInspector(): void {
    const current = this.state.current;
    if (current === null) return;
    const q = current.question;
    this.element("inspector-id").textContent = String(q.id);
    const source = q.source !== null && typeof q.source === "object" && !Array.isArray(q.source)
      ? q.source as Record<string, JsonValue>
      : {};
    const topics = Array.isArray(q.topics) ? q.topics.filter((item): item is string => typeof item === "string") : [];
    const types = ["single_choice", "multiple_choice", "true_false", "fill_blank", "calculation", "short_answer", "proof", "essay", "composite", "other"];
    const statuses = ["draft", "reviewed", "verified", "deprecated"];
    this.element("metadata-form").innerHTML = `
      <label>标题<input name="title" value="${escapeHtml(String(q.title))}" required /></label>
      <div class="metadata-grid"><label>学科<input name="subject" value="${escapeHtml(String(q.subject))}" required /></label><label>章节<input name="chapter" value="${escapeHtml(String(q.chapter ?? ""))}" /></label></div>
      <div class="metadata-grid"><label>题型<select name="type">${types.map((value) => `<option value="${value}"${q.type === value ? " selected" : ""}>${value}</option>`).join("")}</select></label><label>状态<select name="status">${statuses.map((value) => `<option value="${value}"${q.status === value ? " selected" : ""}>${value}</option>`).join("")}</select></label></div>
      <label>难度<input name="difficulty" type="number" min="1" max="5" value="${escapeHtml(String(q.difficulty))}" required /></label>
      <label>标签（逗号分隔）<input name="topics" value="${escapeHtml(topics.join(", "))}" required /></label>
      <div class="metadata-grid"><label>来源类型<input name="sourceType" value="${escapeHtml(String(source.type ?? "manual"))}" required /></label><label>来源引用<input name="sourceReference" value="${escapeHtml(String(source.reference ?? ""))}" /></label></div>
      <button class="compact-button primary-action" type="submit">应用属性</button>`;
    const assets = this.element("asset-list");
    assets.innerHTML = this.state.assets.length === 0 ? '<p class="muted">没有图形资产。可粘贴或拖入图片。</p>' : "";
    for (const asset of this.state.assets) {
      const card = document.createElement("article");
      card.className = `asset-card asset-${asset.kind}${asset.diagnostic === null ? "" : ` ${asset.diagnostic.severity}`}`;
      const status = asset.kind === "logical"
        ? `${asset.status} · ${asset.preferredRepresentation ?? "无首选表示"}`
        : asset.kind === "local"
          ? `本地资源 · ${asset.declared ? "已声明" : "仅正文引用"}`
          : asset.kind === "external"
            ? "外部资源 · 只读"
            : "资源引用无效";
      const diagnostic = asset.diagnostic === null
        ? ""
        : `<small class="asset-diagnostic">${escapeHtml(asset.diagnostic.message)}</small>`;
      card.innerHTML = `${asset.previewDataUrl === null ? `<div class="asset-placeholder">${icon("image")}</div>` : `<img src="${asset.previewDataUrl}" alt="${escapeHtml(asset.displayName)} 预览" />`}<div class="asset-card-body"><strong>${escapeHtml(asset.displayName)}</strong><span>${escapeHtml(status)}</span>${diagnostic}</div><button class="asset-menu-button" aria-label="${escapeHtml(asset.displayName)} 操作" title="资源操作">${icon("more")}</button><div class="asset-menu" hidden></div>`;
      const menu = card.querySelector<HTMLElement>(".asset-menu");
      const menuButton = card.querySelector<HTMLButtonElement>(".asset-menu-button");
      if (menu !== null && menuButton !== null) {
        const openAction = asset.kind === "logical" ? "open" : "open_reference";
        const revealAction = asset.kind === "logical" ? "reveal" : "reveal_reference";
        const openLabel = asset.kind === "external"
          ? "在浏览器中打开"
          : asset.kind === "local"
            ? "打开文件"
            : "打开原图";
        const actions = [
          [openAction, openLabel, asset.capabilities.canOpen],
          ["edit_ipe", "用 Ipe 编辑", asset.capabilities.canEditIpe],
          ["reconcile", "检测修改并重渲染", asset.capabilities.canEditIpe],
          ["replace", "替换为本地文件", asset.capabilities.canReplace],
          ["replace_clipboard", "从剪贴板替换", asset.capabilities.canReplace],
          ["render", "重新渲染", asset.capabilities.canRender],
          [revealAction, "在资源管理器中显示", asset.capabilities.canReveal],
        ] as const;
        for (const [action, label, enabled] of actions) {
          const button = document.createElement("button");
          button.type = "button";
          button.disabled = !enabled;
          button.textContent = label;
          button.title = enabled ? label : `${label}：当前资源不支持`;
          button.addEventListener("click", () => {
            menu.hidden = true;
            void this.assetAction(asset, action);
          });
          menu.append(button);
        }
        menuButton.addEventListener("click", () => {
          const shouldOpen = menu.hidden;
          for (const other of this.root.querySelectorAll<HTMLElement>(".asset-menu")) other.hidden = true;
          menu.hidden = !shouldOpen;
        });
      }
      assets.append(card);
    }
    const history = this.element("history-list");
    history.innerHTML = this.state.history.length === 0 ? '<p class="muted">尚无历史记录</p>' : this.state.history.slice(-6).reverse().map((item) => `<div class="history-entry"><strong>${escapeHtml(item.operation)}</strong><span>${escapeHtml(formatTimestamp(item.timestamp))}</span><small>${escapeHtml(item.fields.join("、") || item.source)}</small></div>`).join("");
  }

  private renderValidation(result: ValidationResult): void {
    const badge = this.element("validation-badge");
    badge.textContent = result.ok ? (result.diagnostics.length === 0 ? "校验通过" : "通过，有提示") : "校验失败";
    badge.className = `validation-badge ${result.ok ? (result.diagnostics.length === 0 ? "success" : "warning") : "error"}`;
    const bar = this.element("diagnostic-bar");
    bar.hidden = result.diagnostics.length === 0;
    bar.innerHTML = result.diagnostics.map((item) => `<div class="diagnostic ${item.severity}"><strong>${escapeHtml(item.code)}</strong><span>${escapeHtml(item.message)}</span></div>`).join("");
  }

  private renderAbout(): void {
    const initialized = this.state.initialized;
    if (initialized === null) return;
    this.element("connection-status").title = `Studio ${initialized.studioVersion}; sidecar ${initialized.sidecarVersion}; qbank ${initialized.coreVersion}; protocol ${initialized.protocolVersion}`;
  }

  private updateDirty(dirty: boolean): void {
    const indicator = this.element("dirty-indicator");
    indicator.textContent = dirty ? "● 未保存" : "已保存";
    indicator.className = `dirty-indicator ${dirty ? "dirty" : "saved"}`;
    this.setEnabled("save", dirty);
    this.setEnabled("validate", this.state.current !== null);
    this.setEnabled("undo", dirty);
    const title = this.state.current?.question.title;
    document.title = `${dirty ? "● " : ""}${typeof title === "string" ? `${title} — ` : ""}QBank Studio`;
  }

  private toggleTheme(): void {
    this.state.theme = this.state.theme === "light" ? "dark" : "light";
    this.root.querySelector<HTMLElement>(".app-shell")?.setAttribute("data-theme", this.state.theme);
    this.editor?.setTheme(this.state.theme === "dark" ? "dark" : "classic");
    if (this.state.current !== null) {
      this.preview?.loading("正在同步预览主题…", this.state.theme);
    } else {
      this.preview?.clear(this.state.theme);
    }
    void this.renderSecurePreview();
  }

  private setLoading(loading: boolean, message = "正在加载题目…"): void {
    this.state.loading = loading;
    const overlay = this.element("loading-overlay");
    overlay.hidden = !loading;
    const strong = overlay.querySelector("strong");
    if (strong !== null) strong.textContent = message;
  }

  private setRepositoryLoading(message: string, stage: string): void {
    const navigation = this.root.querySelector<HTMLElement>(".navigation");
    navigation?.classList.toggle("repository-loading", Boolean(message));
    if (navigation !== null) navigation.ariaBusy = String(Boolean(message));
    const workspace = this.root.querySelector<HTMLElement>(".document-workspace");
    const inspector = this.root.querySelector<HTMLElement>(".inspector");
    if (workspace !== null) workspace.inert = Boolean(message);
    if (inspector !== null) inspector.inert = Boolean(message);
    this.setEnabled("open-repository", !message);
    if (message) {
      this.element("result-count").textContent = message;
      this.element("connection-status").textContent = stage;
      this.element("connection-status").className = "connection loading";
    } else if (this.state.repository !== null) {
      this.element("connection-status").textContent = "已连接";
      this.element("connection-status").className = "connection success";
    }
  }

  private setConnection(text: string, kind: "success" | "error"): void {
    const element = this.element("connection-status");
    element.textContent = text;
    element.className = `connection ${kind}`;
  }

  private showSidecarFailure(reason: string): void {
    this.setConnection("sidecar 已停止", "error");
    this.toast(`${reason}。请重新启动 Studio；未保存内容仍保留在编辑器中。`, "error", 0);
    this.setEnabled("save", false);
    this.setEnabled("validate", false);
  }

  private toast(message: string, kind: "success" | "warning" | "error", duration = 4200): void {
    const toast = document.createElement("div");
    toast.className = `toast ${kind}`;
    toast.textContent = message;
    this.element("toast-region").append(toast);
    if (duration > 0) window.setTimeout(() => toast.remove(), duration);
  }

  private setEnabled(id: string, enabled: boolean): void {
    const element = this.element(id) as HTMLButtonElement | HTMLInputElement;
    element.disabled = !enabled;
  }

  private element(id: string): HTMLElement {
    const element = this.root.querySelector<HTMLElement>(`#${id}`);
    if (element === null) throw new Error(`missing element: ${id}`);
    return element;
  }
}

async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function splitCommaValues(value: string): string[] {
  return [...new Set(value.split(/[,，]/).map((item) => item.trim()).filter(Boolean))];
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character] ?? character);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function isRepairableIndexError(error: unknown): boolean {
  if (!(error instanceof SidecarRpcError) || error.data === null || typeof error.data !== "object") {
    return false;
  }
  const data = error.data as { canRebuildIndex?: unknown };
  return data.canRebuildIndex === true;
}

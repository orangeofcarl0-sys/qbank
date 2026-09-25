/** Paper selection, editing, validation, and export features of Studio. */
import { save as chooseSavePath } from "@tauri-apps/plugin-dialog";
import type { JsonValue, PaperDocument, PaperSummary, PaperValidationResult } from "./protocol";
import { escapeHtml } from "./ui-utils";
import type { StudioApp } from "./studio-app";

export class PaperManagement {
  constructor(private readonly app: StudioApp) {}

  async openPaperManager(): Promise<void> {
    try {
      this.app.state.papers = await this.app.bridge.request<PaperSummary[]>("paper.list");
      const select = this.app.element("paper-select") as HTMLSelectElement;
      select.innerHTML = '<option value="">选择试卷…</option>' + this.app.state.papers.map((paper) => `<option value="${escapeHtml(paper.path)}">${escapeHtml(paper.title)}</option>`).join("");
      this.renderPaperSummary();
      (this.app.element("paper-dialog") as HTMLDialogElement).showModal();
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  async selectPaper(): Promise<void> {
    const path = (this.app.element("paper-select") as HTMLSelectElement).value;
    if (!path) {
      this.app.state.currentPaper = null;
      this.renderPaperSummary();
      return;
    }
    this.app.state.currentPaper = await this.app.bridge.request<PaperDocument>("paper.get", { path });
    this.renderPaperSummary();
  }

  renderPaperSummary(): void {
    const host = this.app.element("paper-summary");
    const paperDocument = this.app.state.currentPaper;
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

  async createPaper(): Promise<void> {
    const selected = [...this.app.state.selectedQuestionIds];
    if (selected.length === 0) return;
    const values = await this.app.promptQuestionDetails("新建试卷", {
      id: "generated/studio-paper.yaml",
      name: "新试卷",
      idPattern: false,
    });
    if (values === null) return;
    try {
      await this.app.bridge.request("paper.create", {
        path: values.id,
        title: values.name,
        questionIds: selected,
        expectedRevision: this.app.repositoryRevision(),
      });
      this.app.state.papers = await this.app.bridge.request<PaperSummary[]>("paper.list");
      const created = this.app.state.papers.find((paper) => paper.path.endsWith(values.id.replaceAll("\\", "/")) || paper.title === values.name);
      if (created !== undefined) {
        (this.app.element("paper-select") as HTMLSelectElement).value = created.path;
        this.app.state.currentPaper = await this.app.bridge.request<PaperDocument>("paper.get", { path: created.path });
      }
      this.renderPaperSummary();
      this.app.toast("试卷已创建", "success");
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  async addSelectedToPaper(): Promise<void> {
    const paper = this.app.state.currentPaper;
    const selected = [...this.app.state.selectedQuestionIds];
    if (paper === null || selected.length === 0) return;
    await this.app.bridge.request("paper.addQuestions", {
      path: paper.path,
      questionIds: selected,
      expectedRevision: paper.revision,
    });
    this.app.state.currentPaper = await this.app.bridge.request<PaperDocument>("paper.get", { path: paper.path });
    this.renderPaperSummary();
    this.app.toast("所选题目已加入试卷", "success");
  }

  async savePaper(): Promise<void> {
    const paper = this.app.state.currentPaper;
    if (paper === null) return;
    const result = await this.app.bridge.request<{ revision: string; paper: Record<string, JsonValue> }>("paper.save", {
      path: paper.path,
      paper: paper.paper,
      expectedRevision: paper.revision,
    });
    this.app.state.currentPaper = { ...paper, paper: result.paper, revision: result.revision };
    this.app.toast("试卷顺序与分值已保存", "success");
  }

  async validatePaper(): Promise<void> {
    const paper = this.app.state.currentPaper;
    if (paper === null) return;
    const report = await this.app.bridge.request<PaperValidationResult>("paper.validate", { path: paper.path });
    const host = this.app.element("paper-diagnostics");
    host.textContent = report.ok ? "试卷校验通过" : report.issues.map((item) => `${item.code}: ${item.message}`).join("\n");
    host.className = `paper-diagnostics ${report.ok ? "success" : "error"}`;
  }

  async exportPaper(withSolutions: boolean): Promise<void> {
    const paper = this.app.state.currentPaper;
    if (paper === null) return;
    const output = await chooseSavePath({
      title: withSolutions ? "导出答案版试卷" : "导出学生版试卷",
      defaultPath: `${paper.path.split("/").at(-1)?.replace(/\.ya?ml$/i, "") ?? "paper"}-${withSolutions ? "solutions" : "student"}.html`,
      filters: [{ name: "HTML", extensions: ["html"] }],
    });
    if (typeof output !== "string") return;
    await this.app.bridge.request("paper.build", {
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
    this.app.toast(`已导出${withSolutions ? "答案版" : "学生版"}试卷`, "success");
  }
}

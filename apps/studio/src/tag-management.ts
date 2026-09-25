/** Tag registry, tag overview, and bulk-mutation features of Studio. */
import { ask } from "@tauri-apps/plugin-dialog";
import {
  displayTag,
  EMPTY_FILTERS,
  normalizeFilters,
  type TagOverview,
  type TagUsage,
  type TaxonomyTag,
} from "./advanced-management";
import type { JsonValue, QuestionMutationResult } from "./protocol";
import { escapeHtml, splitCommaValues } from "./ui-utils";
import type { StudioApp } from "./studio-app";

export class TagManagement {
  constructor(private readonly app: StudioApp) {}

  openTagManager(): void {
    this.renderTagManager();
    (this.app.element("tag-manager-dialog") as HTMLDialogElement).showModal();
  }

  renderTagManager(): void {
    const host = this.app.element("tag-manager-list");
    const query = (this.app.element("tag-manager-search") as HTMLInputElement).value
      .trim()
      .toLocaleLowerCase("zh-CN");
    const tags = this.app.state.tags.filter((tag) => {
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

  async editTag(usage?: TagUsage): Promise<void> {
    const dialog = this.app.element("tag-editor-dialog") as HTMLDialogElement;
    const metadata = usage?.metadata;
    this.app.element("tag-editor-title").textContent = metadata === undefined ? "新建标签" : "编辑标签";
    const slug = this.app.element("tag-editor-slug") as HTMLInputElement;
    slug.value = usage?.slug ?? "";
    slug.readOnly = metadata !== undefined;
    (this.app.element("tag-editor-name-zh") as HTMLInputElement).value = metadata?.name_zh ?? "";
    (this.app.element("tag-editor-name-en") as HTMLInputElement).value = metadata?.name_en ?? "";
    (this.app.element("tag-editor-aliases") as HTMLInputElement).value = metadata?.aliases.join(", ") ?? "";
    (this.app.element("tag-editor-description") as HTMLTextAreaElement).value = metadata?.description ?? "";
    (this.app.element("tag-editor-status") as HTMLSelectElement).value = metadata?.status ?? "active";
    dialog.returnValue = "";
    dialog.showModal();
    await new Promise<void>((resolve) => dialog.addEventListener("close", () => resolve(), { once: true }));
    if (dialog.returnValue !== "confirm") return;
    const tag: TaxonomyTag = {
      slug: slug.value.trim(),
      name_zh: (this.app.element("tag-editor-name-zh") as HTMLInputElement).value.trim() || undefined,
      name_en: (this.app.element("tag-editor-name-en") as HTMLInputElement).value.trim() || undefined,
      aliases: (this.app.element("tag-editor-aliases") as HTMLInputElement).value
        .split(",").map((item) => item.trim()).filter(Boolean),
      description: (this.app.element("tag-editor-description") as HTMLTextAreaElement).value.trim() || undefined,
      status: (this.app.element("tag-editor-status") as HTMLSelectElement).value as TaxonomyTag["status"],
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

  async renameTag(slug: string): Promise<void> {
    const values = await this.app.promptTextAction({
      title: "重命名标签",
      description: `将 ${slug} 原子重命名，并在所有已引用题目中同步。`,
      primaryLabel: "新 slug",
    });
    if (values === null) return;
    await this.runTaxonomyMutation("taxonomy.rename", { old: slug, new: values.primary });
  }

  async mergeTag(source: string): Promise<void> {
    const values = await this.app.promptTextAction({
      title: "合并标签",
      description: `将 ${source} 的全部引用合并到目标标签。`,
      primaryLabel: "目标 slug",
      suggestTags: true,
    });
    if (values === null) return;
    await this.runTaxonomyMutation("taxonomy.merge", { source, target: values.primary });
  }

  async deleteTag(slug: string): Promise<void> {
    const confirmed = await ask(
      `删除标签“${slug}”并从所有题目移除该引用？此操作会写入统一历史。`,
      { title: "删除标签", kind: "warning" },
    );
    if (!confirmed) return;
    await this.runTaxonomyMutation("taxonomy.delete", { value: slug });
  }

  async runTaxonomyMutation( method: string, params: Record<string, JsonValue>, ): Promise<void> {
    try {
      const result = await this.app.bridge.request<QuestionMutationResult>(method, {
        ...params,
        expectedRevision: this.app.repositoryRevision(),
      });
      if (!result.ok || result.revision === undefined) return;
      this.app.updateRepositoryRevision(result.revision);
      await this.app.refreshQuestionInventory();
      this.renderTagManager();
      this.app.toast("标签操作已提交", "success");
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  async openTagOverview(): Promise<void> {
    const overview = await this.app.bridge.request<TagOverview>("taxonomy.overview", { topN: 20 });
    const host = this.app.element("tag-overview-content");
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
    (this.app.element("tag-overview-dialog") as HTMLDialogElement).showModal();
  }

  renderCoverage( host: HTMLElement, cells: TagOverview["year_coverage"], key: "year" | "chapter", ): void {
    const grid = document.createElement("div");
    grid.className = "coverage-grid";
    for (const cell of cells.slice(0, 80)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "overview-cell";
      button.textContent = `${cell.axis} · ${cell.tag} · ${cell.count}`;
      button.addEventListener("click", () => {
        this.app.state.selectedView = "all";
        this.app.state.specialViewIds = null;
        this.app.state.filters = normalizeFilters({
          ...EMPTY_FILTERS,
          topics: [cell.tag],
          [key]: key === "year" ? Number(cell.axis) : cell.axis,
        });
        (this.app.element("tag-overview-dialog") as HTMLDialogElement).close();
        this.app.writeFilterControls();
        void this.app.refreshFilteredQuestions();
      });
      grid.append(button);
    }
    host.append(grid);
  }

  applyOverviewTopics(topics: string[]): void {
    this.app.state.selectedView = "all";
    this.app.state.specialViewIds = null;
    this.app.state.filters = normalizeFilters({ ...EMPTY_FILTERS, topics, topicMode: "and" });
    (this.app.element("tag-overview-dialog") as HTMLDialogElement).close();
    this.app.writeFilterControls();
    void this.app.refreshFilteredQuestions();
  }

  async bulkEditTags(): Promise<void> {
    if (this.app.state.selectedQuestionIds.size === 0) return;
    const values = await this.app.promptTextAction({
      title: "批量修改标签",
      description: `仅修改已明确选择的 ${this.app.state.selectedQuestionIds.size} 道题。`,
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

  async bulkUpdateField(field: "status" | "chapter"): Promise<void> {
    if (this.app.state.selectedQuestionIds.size === 0) return;
    const values = await this.app.promptTextAction({
      title: field === "status" ? "批量修改状态" : "批量修改章节",
      description: `仅修改已明确选择的 ${this.app.state.selectedQuestionIds.size} 道题。`,
      primaryLabel: field === "status" ? "状态" : "章节",
    });
    if (values === null) return;
    await this.runBulkMutation("question.bulkUpdate", { set: { [field]: values.primary } });
  }

  async runBulkMutation( method: string, params: Record<string, JsonValue>, ): Promise<void> {
    try {
      const count = this.app.state.selectedQuestionIds.size;
      const result = await this.app.bridge.request<QuestionMutationResult>(method, {
        ...params,
        questionIds: [...this.app.state.selectedQuestionIds],
        expectedRevision: this.app.repositoryRevision(),
      });
      if (!result.ok || result.revision === undefined) return;
      this.app.updateRepositoryRevision(result.revision);
      await this.app.refreshQuestionInventory();
      this.app.toast(`已更新 ${count} 道题`, "success");
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }
}

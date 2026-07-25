import fixtureSource from "../fixtures/roundtrip/all-features.md?raw";
import type {
  AssetItem,
  InitializeResult,
  JsonValue,
  QuestionDocument,
  QuestionSummary,
  RepositoryStatus,
  RpcBridge,
} from "./protocol";

const QUESTION: QuestionSummary = {
  id: "TEST-ROUNDTRIP-0001",
  title: "Round-trip 合成样例",
  subject: "testing",
  chapter: "editor",
  topics: ["roundtrip"],
  type: "short_answer",
  status: "draft",
  difficulty: 1,
  language: "zh-CN",
  createdAt: "2026-01-15T00:00:00Z",
};

const SLOW_QUESTION: QuestionSummary = {
  ...QUESTION,
  id: "TEST-SLOW-0002",
  title: "Slow generation sample",
  subject: "physics",
  chapter: "optics",
  topics: ["generation", "optics"],
  status: "reviewed",
  difficulty: 4,
  language: "en-US",
  createdAt: "2025-03-12T00:00:00Z",
};

const SLOW_SOURCE = fixtureSource
  .replaceAll(QUESTION.id, SLOW_QUESTION.id)
  .replace(QUESTION.title, SLOW_QUESTION.title);

const DOCUMENT_DATA = {
  schema_version: "1.0",
  ...QUESTION,
  language: "zh-CN",
  source: { type: "synthetic" },
  assets: ["qbank-asset:diagram-1"],
  stem_md: "Round-trip 合成样例",
  options_md: "",
  answer_md: "答案。",
  solution_md: "解析。",
  rubric_md: "要点。",
  review_notes_md: "备注。",
};

const SVG = `data:image/svg+xml;base64,${btoa('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" rx="8" fill="#e4eef6"/><path d="M10 45 Q40 5 70 45 T130 45" fill="none" stroke="#3d7199" stroke-width="4"/></svg>')}`;

export class FixtureRpcBridge implements RpcBridge {
  private source = fixtureSource;
  private revision = "fixture-1";
  private listeners = new Set<(reason: string) => void>();
  private createdAssets: AssetItem[] = [];
  readonly requestLog: string[] = [];

  async start(): Promise<InitializeResult> {
    return {
      studioVersion: "0.3.0-beta.1",
      sidecarVersion: "fixture",
      coreVersion: "0.3.0b1",
      protocolVersion: "1.0",
      schemaVersions: { question: "1.0", asset: "1.0", paper: "1.0" },
      capabilities: ["fixture"],
    };
  }

  async request<T>(method: string, params: Record<string, JsonValue> = {}): Promise<T> {
    this.requestLog.push(method);
    const identity = String(params.id ?? params.questionId ?? "");
    if (identity === SLOW_QUESTION.id && ["question.get", "asset.list", "history.list"].includes(method)) {
      await new Promise((resolve) => window.setTimeout(resolve, 180));
    } else {
      await Promise.resolve();
    }
    const result = this.result(method, params);
    return result as T;
  }

  async stop(): Promise<void> {}

  onExit(listener: (reason: string) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  simulateExit(reason = "synthetic sidecar crash"): void {
    for (const listener of this.listeners) listener(reason);
  }

  private result(method: string, params: Record<string, JsonValue>): unknown {
    const repository: RepositoryStatus = {
      root: "fixture://synthetic-bank",
      name: "公开合成题库",
      revision: this.revision,
      healthy: true,
      questionCount: 1,
      validationErrors: 0,
      indexDirty: false,
      mathMacros: { qop: "\\operatorname{qbank}" },
      studioWarnings: [],
    };
    const selectedId = String(params.id ?? "");
    const isSlow = selectedId === SLOW_QUESTION.id;
    const document: QuestionDocument = {
      question: isSlow ? { ...DOCUMENT_DATA, ...SLOW_QUESTION } : DOCUMENT_DATA,
      source: isSlow ? SLOW_SOURCE : this.source,
      revision: this.revision,
      diagnostics: [],
    };
    const asset: AssetItem = {
      assetId: "diagram-1",
      role: "figure",
      status: "final",
      preferredRepresentation: "render-svg",
      previewDataUrl: SVG,
      capabilities: {
        canEditIpe: false,
        canReplace: true,
        canOpen: true,
        canRender: false,
        canReveal: true,
      },
      representations: [
        { representationId: "render-svg", format: "svg", stale: false, editable: false, renderable: true },
      ],
    };
    switch (method) {
      case "repository.open": return repository;
      case "repository.status": return repository;
      case "question.list": {
        const rows = [QUESTION, SLOW_QUESTION];
        const topics = Array.isArray(params.topics) ? params.topics.map(String) : [];
        const excluded = Array.isArray(params.excludedTopics) ? params.excludedTopics.map(String) : [];
        const mode = params.topicMode === "or" ? "or" : "and";
        return rows.filter((row) => {
          const text = String(params.text ?? "").toLocaleLowerCase();
          const year = params.year === null || params.year === undefined ? "" : String(params.year);
          const included = topics.length === 0
            || (mode === "or" ? topics.some((topic) => row.topics.includes(topic)) : topics.every((topic) => row.topics.includes(topic)));
          return included
            && !excluded.some((topic) => row.topics.includes(topic))
            && (!text || `${row.id} ${row.title}`.toLocaleLowerCase().includes(text))
            && (!params.subject || row.subject === params.subject)
            && (!params.chapter || row.chapter === params.chapter)
            && (!params.status || row.status === params.status)
            && (!params.type || row.type === params.type)
            && (!params.language || row.language === params.language)
            && (!year || row.createdAt?.startsWith(year))
            && (params.difficultyMin === null || params.difficultyMin === undefined || row.difficulty >= Number(params.difficultyMin))
            && (params.difficultyMax === null || params.difficultyMax === undefined || row.difficulty <= Number(params.difficultyMax));
        });
      }
      case "question.search": return [QUESTION, SLOW_QUESTION];
      case "question.get": return document;
      case "question.validate": return { ok: true, diagnostics: [], canonicalChanged: false };
      case "question.save":
        this.source = String(params.source ?? this.source);
        this.revision = `fixture-${Date.now()}`;
        return { ok: true, diagnostics: [], canonicalChanged: false, revision: this.revision, source: this.source, indexUpdated: true };
      case "question.update": {
        this.revision = `fixture-${Date.now()}`;
        const set = params.set !== null && typeof params.set === "object" && !Array.isArray(params.set)
          ? params.set
          : {};
        return {
          ok: true,
          question: { ...DOCUMENT_DATA, ...set, topics: params.topics ?? DOCUMENT_DATA.topics },
          source: this.source,
          revision: this.revision,
        };
      }
      case "question.create":
      case "question.copy":
      case "question.import":
      case "question.delete":
        this.revision = `fixture-${Date.now()}`;
        return { ok: true, revision: this.revision, dryRun: { dry_run: true }, result: { dry_run: false } };
      case "taxonomy.list": return [
        {
          slug: "roundtrip",
          count: 1,
          registered: true,
          metadata: {
            slug: "roundtrip",
            name_zh: "往返保护",
            aliases: ["round-trip"],
            description: "编辑器往返保护",
            status: "active",
          },
        },
        {
          slug: "optics",
          count: 1,
          registered: true,
          metadata: {
            slug: "optics",
            name_zh: "光学",
            aliases: [],
            description: "光学题目",
            status: "active",
          },
        },
        {
          slug: "zero-count",
          count: 0,
          registered: true,
          metadata: {
            slug: "zero-count",
            name_zh: "零计数标签",
            aliases: [],
            status: "active",
          },
        },
      ];
      case "taxonomy.suggest": return this.result("taxonomy.list", params);
      case "taxonomy.overview": return {
        frequencies: this.result("taxonomy.list", params),
        cooccurrences: [{ left: "generation", right: "optics", count: 1 }],
        year_coverage: [{ axis: "2025", tag: "optics", count: 1 }],
        chapter_coverage: [{ axis: "optics", tag: "optics", count: 1 }],
      };
      case "taxonomy.update":
      case "taxonomy.rename":
      case "taxonomy.merge":
      case "taxonomy.delete":
      case "taxonomy.bulkEdit":
      case "question.bulkUpdate":
        this.revision = `fixture-${Date.now()}`;
        return { ok: true, revision: this.revision, dryRun: { dry_run: true }, result: { dry_run: false } };
      case "view.list": return [
        { name: "all", filters: {}, kind: "filter", protected: true },
        { name: "draft", filters: { status: "draft" }, kind: "filter", protected: true },
        {
          name: "光学复核",
          filters: { subject: "physics", status: "reviewed", topics: ["optics"] },
          kind: "filter",
          protected: false,
        },
      ];
      case "view.apply": return [SLOW_QUESTION];
      case "view.save":
      case "view.rename":
      case "view.delete":
        this.revision = `fixture-${Date.now()}`;
        return { ok: true, revision: this.revision, dryRun: { dry_run: true }, result: { dry_run: false } };
      case "asset.list": return String(params.questionId ?? "") === SLOW_QUESTION.id
        ? []
        : [asset, ...this.createdAssets];
      case "history.list": return [];
      case "asset.open": return { ok: true, revision: this.revision };
      case "asset.replace":
        this.revision = `fixture-${Date.now()}`;
        return { ok: true, revision: this.revision };
      case "asset.render":
      case "asset.reconcile": return { ok: true, revision: this.revision };
      case "asset.create": {
        this.source = String(params.source ?? this.source);
        this.revision = `fixture-${Date.now()}`;
        const assetId = String(params.assetId ?? "figure");
        if (!this.createdAssets.some((item) => item.assetId === assetId)) {
          this.createdAssets.push({ ...asset, assetId });
        }
        return { ok: true, revision: this.revision };
      }
      case "paper.list": return [{
        path: "papers/generated/synthetic-paper.yaml",
        title: "合成试卷",
        questionIds: [QUESTION.id],
        totalScore: 5,
      }];
      case "paper.get": return {
        path: String(params.path),
        revision: this.revision,
        paper: {
          schema_version: "1.0",
          title: "合成试卷",
          language: "zh-CN",
          metadata: { total_score: 5 },
          sections: [{ title: "题目", questions: [{ id: QUESTION.id, score: 5 }] }],
          options: {},
        },
      };
      case "paper.create":
      case "paper.save":
      case "paper.addQuestions":
        this.revision = `fixture-${Date.now()}`;
        return { ok: true, revision: this.revision, paper: params.paper ?? {} };
      case "paper.validate": return { ok: true, issues: [] };
      case "paper.build": return { ok: true, revision: this.revision, result: { ok: true } };
      case "application.shutdown": return { ok: true };
      default: throw new Error(`fixture method not implemented: ${method}`);
    }
  }
}

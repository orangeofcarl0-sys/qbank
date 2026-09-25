/** Shared UI state container for the Studio application shell. */
import {
  normalizeFilters,
  EMPTY_FILTERS,
  type QueryFilters,
  type SavedView,
  type TagUsage,
} from "./advanced-management";
import type {
  AssetItem,
  HistoryEntry,
  InitializeResult,
  PaperDocument,
  PaperSummary,
  QuestionDocument,
  QuestionSummary,
  RepositoryStatus,
  ValidationResult,
} from "./protocol";
import type { EditorMode } from "./editor-buffer";

export interface AppState {
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

export const EMPTY_STATE: AppState = {
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

export const COMMON_MATH_MACROS: Record<string, string | [string, number]> = {
  RR: "\\mathbb{R}",
  NN: "\\mathbb{N}",
  ZZ: "\\mathbb{Z}",
  QQ: "\\mathbb{Q}",
  CC: "\\mathbb{C}",
  abs: ["\\left|#1\\right|", 1],
  norm: ["\\left\\lVert#1\\right\\rVert", 1],
  qbankasset: "\\mathrm{asset}",
};

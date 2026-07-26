import type { SavedView, TagUsage } from "./advanced-management";

export const STUDIO_PROTOCOL_VERSION = "1.0" as const;

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface Diagnostic {
  severity: "error" | "warning";
  code: string;
  message: string;
  field?: string;
}

export interface InitializeResult {
  studioVersion: string;
  sidecarVersion: string;
  coreVersion: string;
  protocolVersion: string;
  schemaVersions: { question: string; asset: string; paper: string };
  capabilities: string[];
}

export interface RepositoryStatus {
  root: string;
  name: string;
  revision: string;
  healthy: boolean;
  questionCount: number;
  validationErrors: number;
  indexDirty: boolean;
  mathMacros: Record<string, string | [string, number]>;
  studioWarnings: string[];
}

export interface RepositoryOpenResult extends RepositoryStatus {
  questions: QuestionSummary[];
  tags: TagUsage[];
  views: SavedView[];
  indexed?: number;
}

export interface QuestionSummary {
  id: string;
  title: string;
  subject: string;
  chapter: string | null;
  topics: string[];
  type: string;
  status: string;
  difficulty: number;
  language: string;
  createdAt: string | null;
}

export interface QuestionDocument {
  question: Record<string, JsonValue>;
  source: string;
  revision: string;
  diagnostics: Diagnostic[];
}

export interface ValidationResult {
  ok: boolean;
  diagnostics: Diagnostic[];
  canonicalChanged: boolean;
}

export interface SaveResult extends ValidationResult {
  revision: string;
  source: string;
  indexUpdated: boolean;
}

export interface AssetRepresentation {
  representationId: string;
  format: string;
  stale: boolean;
  editable: boolean;
  renderable: boolean;
}

export interface AssetItem {
  assetId: string;
  kind: "logical" | "local" | "external" | "invalid";
  reference: string;
  displayName: string;
  declared: boolean;
  exists: boolean;
  diagnostic: Diagnostic | null;
  role: string;
  status: string;
  preferredRepresentation: string | null;
  previewDataUrl: string | null;
  capabilities: {
    canEditIpe: boolean;
    canReplace: boolean;
    canOpen: boolean;
    canRender: boolean;
    canReveal: boolean;
  };
  representations: AssetRepresentation[];
}

export interface HistoryEntry {
  timestamp: string;
  operation: string;
  source: string;
  fields: string[];
}

export interface QuestionMutationResult {
  ok: boolean;
  revision?: string;
  source?: string;
  question?: Record<string, JsonValue>;
  document?: QuestionDocument;
  dryRun?: Record<string, JsonValue>;
  result?: Record<string, JsonValue>;
}

export interface PaperSummary {
  path: string;
  title: string;
  questionIds: string[];
  totalScore: number;
}

export interface PaperDocument {
  path: string;
  paper: Record<string, JsonValue>;
  revision: string;
}

export interface PaperValidationResult {
  ok: boolean;
  issues: Diagnostic[];
  summary?: Record<string, JsonValue>;
}

export interface RpcBridge {
  start(): Promise<InitializeResult>;
  request<T>(method: string, params?: Record<string, JsonValue>): Promise<T>;
  stop(): Promise<void>;
  onExit(listener: (reason: string) => void): () => void;
}

import type { JsonValue, QuestionSummary } from "./protocol";

export type TopicMode = "and" | "or";

export interface QueryFilters {
  text: string;
  subject: string;
  chapter: string;
  topics: string[];
  excludedTopics: string[];
  topicMode: TopicMode;
  type: string;
  status: string;
  difficultyMin: number | null;
  difficultyMax: number | null;
  language: string;
  year: number | null;
}

export interface SavedView {
  name: string;
  filters: Partial<QueryFilters>;
  kind: "filter" | "needs_redraw" | "current_paper";
  protected: boolean;
}

export interface TaxonomyTag {
  slug: string;
  name_zh?: string;
  name_en?: string;
  aliases: string[];
  description?: string;
  status: "active" | "pending" | "deprecated";
  color?: string;
  parent?: string;
}

export interface TagUsage {
  slug: string;
  count: number;
  registered: boolean;
  metadata?: TaxonomyTag;
}

export interface TagCooccurrence {
  left: string;
  right: string;
  count: number;
}

export interface TagCoverageCell {
  axis: string;
  tag: string;
  count: number;
}

export interface TagOverview {
  frequencies: TagUsage[];
  cooccurrences: TagCooccurrence[];
  year_coverage: TagCoverageCell[];
  chapter_coverage: TagCoverageCell[];
}

export interface FilterChip {
  key: keyof QueryFilters;
  value: string;
  label: string;
}

export const EMPTY_FILTERS: QueryFilters = {
  text: "",
  subject: "",
  chapter: "",
  topics: [],
  excludedTopics: [],
  topicMode: "and",
  type: "",
  status: "",
  difficultyMin: null,
  difficultyMax: null,
  language: "",
  year: null,
};

export function normalizeFilters(value: Partial<QueryFilters> | null | undefined): QueryFilters {
  const input = value ?? {};
  const wire = input as unknown as Record<string, unknown>;
  return {
    text: cleanText(input.text),
    subject: cleanText(input.subject),
    chapter: cleanText(input.chapter),
    topics: uniqueText(input.topics),
    excludedTopics: uniqueText(input.excludedTopics ?? wire.excluded_topics),
    topicMode: (input.topicMode ?? wire.topic_mode) === "or" ? "or" : "and",
    type: cleanText(input.type ?? wire.question_type),
    status: cleanText(input.status),
    difficultyMin: validDifficulty(input.difficultyMin ?? wire.difficulty_min),
    difficultyMax: validDifficulty(input.difficultyMax ?? wire.difficulty_max),
    language: cleanText(input.language),
    year: validYear(input.year),
  };
}

export function filtersToRpc(filters: QueryFilters, limit = 20_000): Record<string, JsonValue> {
  return {
    text: filters.text || null,
    subject: filters.subject || null,
    chapter: filters.chapter || null,
    topics: filters.topics,
    excludedTopics: filters.excludedTopics,
    topicMode: filters.topicMode,
    type: filters.type || null,
    status: filters.status || null,
    difficultyMin: filters.difficultyMin,
    difficultyMax: filters.difficultyMax,
    language: filters.language || null,
    year: filters.year,
    offset: 0,
    limit,
  };
}

export function filtersEqual(left: QueryFilters, right: QueryFilters): boolean {
  return JSON.stringify(canonicalFilters(left)) === JSON.stringify(canonicalFilters(right));
}

export function filterChips(filters: QueryFilters): FilterChip[] {
  const chips: FilterChip[] = [];
  const scalar: Array<[keyof QueryFilters, string, string]> = [
    ["text", filters.text, "搜索"],
    ["subject", filters.subject, "学科"],
    ["chapter", filters.chapter, "章节"],
    ["status", filters.status, "状态"],
    ["type", filters.type, "题型"],
    ["language", filters.language, "语言"],
  ];
  for (const [key, value, label] of scalar) {
    if (value) chips.push({ key, value, label: `${label}：${value}` });
  }
  if (filters.year !== null) {
    chips.push({ key: "year", value: String(filters.year), label: `年份：${filters.year}` });
  }
  if (filters.difficultyMin !== null || filters.difficultyMax !== null) {
    const minimum = filters.difficultyMin ?? 1;
    const maximum = filters.difficultyMax ?? 5;
    chips.push({
      key: "difficultyMin",
      value: `${minimum}-${maximum}`,
      label: `难度：${minimum}–${maximum}`,
    });
  }
  for (const topic of filters.topics) {
    chips.push({ key: "topics", value: topic, label: `+ ${topic}` });
  }
  for (const topic of filters.excludedTopics) {
    chips.push({ key: "excludedTopics", value: topic, label: `− ${topic}` });
  }
  if (filters.topics.length > 1) {
    chips.push({
      key: "topicMode",
      value: filters.topicMode,
      label: `标签：${filters.topicMode.toUpperCase()}`,
    });
  }
  return chips;
}

export function removeFilterChip(filters: QueryFilters, chip: FilterChip): QueryFilters {
  const next = normalizeFilters(filters);
  if (chip.key === "topics") next.topics = next.topics.filter((item) => item !== chip.value);
  else if (chip.key === "excludedTopics") {
    next.excludedTopics = next.excludedTopics.filter((item) => item !== chip.value);
  } else if (chip.key === "difficultyMin") {
    next.difficultyMin = null;
    next.difficultyMax = null;
  } else if (chip.key === "topicMode") {
    next.topicMode = "and";
  } else if (chip.key === "year") {
    next.year = null;
  } else {
    (next as unknown as Record<string, string>)[chip.key] = "";
  }
  return next;
}

export function facetValues(
  inventory: QuestionSummary[],
  visible: QuestionSummary[],
  key: "subject" | "chapter" | "status" | "type" | "language" | "year" | "difficulty",
): Array<{ value: string; count: number }> {
  const known = new Set<string>();
  const counts = new Map<string, number>();
  for (const row of inventory) {
    const value = facetValue(row, key);
    if (value !== "") known.add(value);
  }
  for (const row of visible) {
    const value = facetValue(row, key);
    if (value !== "") counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...known]
    .sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true }))
    .map((value) => ({ value, count: counts.get(value) ?? 0 }));
}

export function displayTag(tag: TagUsage): string {
  return tag.metadata?.name_zh ?? tag.metadata?.name_en ?? tag.slug;
}

function facetValue(
  row: QuestionSummary,
  key: "subject" | "chapter" | "status" | "type" | "language" | "year" | "difficulty",
): string {
  if (key === "year") return row.createdAt?.slice(0, 4) ?? "";
  if (key === "difficulty") return String(row.difficulty);
  if (key === "chapter") return row.chapter ?? "";
  return String(row[key] ?? "");
}

function canonicalFilters(filters: QueryFilters): QueryFilters {
  return {
    ...normalizeFilters(filters),
    topics: [...filters.topics].sort(),
    excludedTopics: [...filters.excludedTopics].sort(),
  };
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function uniqueText(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean))];
}

function validDifficulty(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 5
    ? value
    : null;
}

function validYear(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 9999
    ? value
    : null;
}

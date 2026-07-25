import { describe, expect, it } from "vitest";
import {
  EMPTY_FILTERS,
  facetValues,
  filterChips,
  filtersEqual,
  normalizeFilters,
  removeFilterChip,
} from "../src/advanced-management";
import type { QuestionSummary } from "../src/protocol";

const questions: QuestionSummary[] = [
  {
    id: "OPT-0001",
    title: "光学",
    subject: "physics",
    chapter: "optics",
    topics: ["interference"],
    type: "short_answer",
    status: "reviewed",
    difficulty: 2,
    language: "zh-CN",
    createdAt: "2025-01-01T00:00:00Z",
  },
  {
    id: "MATH-0001",
    title: "代数",
    subject: "math",
    chapter: "algebra",
    topics: ["linear-algebra"],
    type: "calculation",
    status: "draft",
    difficulty: 4,
    language: "en-US",
    createdAt: "2024-01-01T00:00:00Z",
  },
];

describe("advanced question management", () => {
  it("normalizes and compares complete filters deterministically", () => {
    const first = normalizeFilters({
      ...EMPTY_FILTERS,
      topics: ["b", "a", "a"],
      excludedTopics: ["c"],
      topicMode: "or",
      difficultyMin: 2,
      difficultyMax: 5,
      year: 2025,
    });
    const second = normalizeFilters({ ...first, topics: ["a", "b"] });
    expect(filtersEqual(first, second)).toBe(true);
    expect(first.topics).toEqual(["b", "a"]);
  });

  it("keeps zero-count facet values visible", () => {
    expect(facetValues(questions, [questions[0]], "subject")).toEqual([
      { value: "math", count: 0 },
      { value: "physics", count: 1 },
    ]);
  });

  it("creates removable chips for every public filter family", () => {
    const filters = normalizeFilters({
      text: "wave",
      subject: "physics",
      topics: ["interference"],
      excludedTopics: ["deprecated"],
      topicMode: "or",
      difficultyMin: 2,
      difficultyMax: 4,
      year: 2025,
    });
    const chips = filterChips(filters);
    expect(chips.map((chip) => chip.label)).toContain("+ interference");
    expect(chips.map((chip) => chip.label)).toContain("− deprecated");
    expect(chips.map((chip) => chip.label)).toContain("难度：2–4");
    const topicChip = chips.find((chip) => chip.key === "topics");
    expect(topicChip).toBeDefined();
    if (topicChip === undefined) throw new Error("topic chip was not created");
    const withoutTopic = removeFilterChip(filters, topicChip);
    expect(withoutTopic.topics).toEqual([]);
    expect(withoutTopic.excludedTopics).toEqual(["deprecated"]);
  });
});

import { describe, expect, it } from "vitest";
import { EditorBuffer } from "../src/editor-buffer";

describe("EditorBuffer", () => {
  it("clears dirty when undo returns byte-for-byte to the saved snapshot", () => {
    const buffer = new EditorBuffer();
    buffer.load("alpha\n");
    expect(buffer.edit("alpha beta\n").dirty).toBe(true);
    expect(buffer.edit("alpha\n").dirty).toBe(false);
  });

  it("rejects stale generation results after a question switch", () => {
    const buffer = new EditorBuffer();
    const first = buffer.load("first");
    const second = buffer.load("second");
    expect(buffer.isCurrent(first.generation)).toBe(false);
    expect(buffer.isCurrent(second.generation)).toBe(true);
  });

  it("accepts authoritative canonical source after save", () => {
    const buffer = new EditorBuffer();
    buffer.load("before");
    buffer.edit("after");
    expect(buffer.markSaved("after\n")).toEqual({
      source: "after\n",
      savedSource: "after\n",
      dirty: false,
      generation: 1,
    });
  });
});

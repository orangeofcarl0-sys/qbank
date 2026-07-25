export type EditorMode = "source" | "split" | "instant";

export interface BufferSnapshot {
  source: string;
  savedSource: string;
  dirty: boolean;
  generation: number;
}

export class EditorBuffer {
  private source = "";
  private savedSource = "";
  private generation = 0;

  load(source: string): BufferSnapshot {
    this.generation += 1;
    this.source = source;
    this.savedSource = source;
    return this.snapshot();
  }

  edit(source: string): BufferSnapshot {
    this.source = source;
    return this.snapshot();
  }

  markSaved(authoritativeSource: string): BufferSnapshot {
    this.source = authoritativeSource;
    this.savedSource = authoritativeSource;
    return this.snapshot();
  }

  isCurrent(generation: number): boolean {
    return generation === this.generation;
  }

  snapshot(): BufferSnapshot {
    return {
      source: this.source,
      savedSource: this.savedSource,
      dirty: this.source !== this.savedSource,
      generation: this.generation,
    };
  }
}

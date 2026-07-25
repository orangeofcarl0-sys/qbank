import { Editor, type BytemdPlugin } from "bytemd";
import "bytemd/dist/index.css";
import source from "../fixtures/roundtrip/all-features.md?raw";

interface ComparisonHarness {
  getValue(): string | null;
}

declare global {
  interface Window {
    __BYTEMD_COMPARISON__: ComparisonHarness;
  }
}

let value: string | null = null;
const capture: BytemdPlugin = {
  editorEffect(context) {
    value = context.editor.getValue();
    context.editor.on("change", (editor) => {
      value = editor.getValue();
    });
  },
};

const target = document.querySelector<HTMLElement>("#bytemd-comparison");
if (target === null) throw new Error("missing ByteMD comparison target");

// ByteMD's published Svelte declaration omits the runtime component constructor.
const ByteMdEditor = Editor as unknown as new (options: {
  target: HTMLElement;
  props: {
    value: string;
    plugins: BytemdPlugin[];
    mode: "split";
    previewDebounce: number;
  };
}) => object;

new ByteMdEditor({
  target,
  props: {
    value: source,
    plugins: [capture],
    mode: "split",
    previewDebounce: 0,
  },
});

window.__BYTEMD_COMPARISON__ = {
  getValue: () => value,
};

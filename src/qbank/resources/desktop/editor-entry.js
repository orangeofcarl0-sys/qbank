import {basicSetup} from "codemirror";
import {EditorState, Compartment} from "@codemirror/state";
import {EditorView, keymap} from "@codemirror/view";
import {markdown} from "@codemirror/lang-markdown";
import {HighlightStyle, StreamLanguage, syntaxHighlighting} from "@codemirror/language";
import {stex} from "@codemirror/legacy-modes/mode/stex";
import {undo, redo, historyKeymap, history} from "@codemirror/commands";
import {tags} from "@lezer/highlight";

const language = new Compartment();
let bridge = null;
let currentMode = "markdown";

const qbankHighlight = HighlightStyle.define([
  {tag: tags.heading, color: "var(--qbank-accent)", fontWeight: "600"},
  {tag: [tags.link, tags.url], color: "var(--qbank-accent-hover)", textDecoration: "underline"},
  {tag: [tags.atom, tags.number], color: "var(--qbank-warning)"},
  {tag: tags.monospace, color: "var(--qbank-success)"},
  {tag: tags.comment, color: "var(--qbank-text-secondary)"},
]);

const changeListener = EditorView.updateListener.of(update => {
  if (!update.docChanged || !bridge) return;
  // Dirty-state and close confirmation depend on the latest document value.
  // Preview rendering is throttled by the desktop layer, so this signal must
  // stay synchronous even during rapid edits and undo/redo.
  bridge.sourceChanged(update.state.doc.toString());
});

function editorState(doc) {
  return EditorState.create({
    doc,
    extensions: [
      basicSetup,
      history(),
      keymap.of(historyKeymap),
      language.of(currentMode === "tex" ? StreamLanguage.define(stex) : markdown()),
      syntaxHighlighting(qbankHighlight),
      changeListener,
      EditorView.lineWrapping,
      EditorView.theme({
        "&": {height: "100%", fontSize: "14px"},
        ".cm-scroller": {
          overflow: "auto",
          fontFamily: '"Cascadia Code", "JetBrains Mono", Consolas, monospace',
          lineHeight: "1.62",
        },
        ".cm-content": {padding: "22px 10px 80px"},
        ".cm-gutters": {
          background: "var(--qbank-surface)",
          color: "var(--qbank-text-disabled)",
          border: "0",
        },
        "&.cm-focused": {outline: "none"},
      }),
    ],
  });
}

const view = new EditorView({
  parent: document.getElementById("editor"),
  state: editorState(""),
});

window.qbankEditor = {
  setValue(value) {
    // Programmatic question loads start a fresh document session. Recreating
    // the state prevents Undo from restoring another question's source.
    view.setState(editorState(value));
  },
  getValue() {
    return view.state.doc.toString();
  },
  undo() {
    return undo(view);
  },
  redo() {
    return redo(view);
  },
  setMode(mode) {
    currentMode = mode;
    view.dispatch({effects: language.reconfigure(
      mode === "tex" ? StreamLanguage.define(stex) : markdown(),
    )});
  },
  insertAsset(assetId) {
    const selection = view.state.selection.main;
    const text = `![${assetId}](qbank-asset:${assetId})`;
    view.dispatch({
      changes: {from: selection.from, to: selection.to, insert: text},
      selection: {anchor: selection.from + text.length},
    });
    view.focus();
  },
  focus() {
    view.focus();
  },
};

new QWebChannel(qt.webChannelTransport, channel => {
  bridge = channel.objects.editorBridge;
  bridge.editorReady();
});

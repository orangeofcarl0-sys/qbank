import {basicSetup} from "codemirror";
import {EditorState, Compartment} from "@codemirror/state";
import {EditorView, keymap} from "@codemirror/view";
import {markdown} from "@codemirror/lang-markdown";
import {StreamLanguage} from "@codemirror/language";
import {stex} from "@codemirror/legacy-modes/mode/stex";
import {undo, redo, historyKeymap, history} from "@codemirror/commands";

const language = new Compartment();
let bridge = null;
let notifyTimer = null;

const changeListener = EditorView.updateListener.of(update => {
  if (!update.docChanged || !bridge) return;
  window.clearTimeout(notifyTimer);
  notifyTimer = window.setTimeout(
    () => bridge.sourceChanged(update.state.doc.toString()),
    120,
  );
});

const view = new EditorView({
  parent: document.getElementById("editor"),
  state: EditorState.create({
    doc: "",
    extensions: [
      basicSetup,
      history(),
      keymap.of(historyKeymap),
      language.of(markdown()),
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
        ".cm-gutters": {background: "#f8f9fb", color: "#9ba3ad", border: "0"},
        "&.cm-focused": {outline: "none"},
      }),
    ],
  }),
});

window.qbankEditor = {
  setValue(value) {
    view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: value}});
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

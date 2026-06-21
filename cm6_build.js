import {EditorState} from "@codemirror/state";
import {EditorView, drawSelection, highlightActiveLine, lineNumbers, keymap} from "@codemirror/view";
import {oneDark} from "@codemirror/theme-one-dark";
import {bracketMatching, defaultHighlightStyle, StreamLanguage, syntaxHighlighting} from "@codemirror/language";
import {javascript as javascriptLegacy} from "@codemirror/legacy-modes/mode/javascript";

const indentWithTab = {
  key: "Tab",
  run(view) {
    view.dispatch(view.state.replaceSelection("  "));
    return true;
  }
};

const basicSetup = [
  lineNumbers(),
  drawSelection(),
  highlightActiveLine(),
  bracketMatching(),
  syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
  keymap.of([indentWithTab])
];

window.CM6 = {
  EditorView,
  EditorState,
  basicSetup,
  javascript: () => StreamLanguage.define(javascriptLegacy),
  oneDark,
  keymap,
  indentWithTab
};

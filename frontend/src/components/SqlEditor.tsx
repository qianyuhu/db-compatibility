import Editor, { type OnMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { useRef, useEffect, useCallback } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onExecute: () => void;
}

export default function SqlEditor({ value, onChange, onExecute }: Props) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const onChangeRef = useRef(onChange);
  const onExecuteRef = useRef(onExecute);
  const lastExternalValue = useRef(value);
  const isMounted = useRef(false);
  // Flag: set true when the change originated from inside the editor
  // (typing / paste / undo). Prevents useEffect from calling model.setValue()
  // which would destroy cursor position and paste formatting.
  const isInternalChange = useRef(false);

  // Keep refs in sync so closures always have the latest callbacks
  onChangeRef.current = onChange;
  onExecuteRef.current = onExecute;

  // Handle external value changes (e.g. "apply rewrite suggestion")
  // WITHOUT interfering with typing / paste / undo inside the editor.
  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true;
      lastExternalValue.current = value;
      return;
    }
    // If the change came from inside the editor (user typed / pasted),
    // just sync the ref and skip — the model already has the right content.
    if (isInternalChange.current) {
      isInternalChange.current = false;
      lastExternalValue.current = value;
      return;
    }
    if (value === lastExternalValue.current) return;
    lastExternalValue.current = value;

    const editor = editorRef.current;
    if (!editor) return;
    const model = editor.getModel();
    if (!model) return;

    // Only overwrite when the model content actually differs
    if (model.getValue() !== value) {
      model.pushStackElement();
      model.setValue(value);
    }
  }, [value]);

  const handleMount: OnMount = useCallback((editor, monaco) => {
    editorRef.current = editor;

    // Set initial value imperatively
    const model = editor.getModel();
    if (model && model.getValue() !== value) {
      model.setValue(value);
    }

    // Listen for content changes — mark as internal so useEffect won't
    // call model.setValue() and destroy paste formatting / cursor position.
    editor.onDidChangeModelContent(() => {
      const model = editor.getModel();
      if (model) {
        const newValue = model.getValue();
        lastExternalValue.current = newValue;
        isInternalChange.current = true;
        onChangeRef.current(newValue);
      }
    });

    // Ctrl/Cmd+Enter to execute
    editor.addAction({
      id: "execute-sql",
      label: "Execute SQL",
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
      run: () => onExecuteRef.current(),
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ border: "1px solid #d9d9d9", borderRadius: 8, overflow: "hidden" }}>
      <div
        style={{
          padding: "6px 12px",
          background: "#fafafa",
          borderBottom: "1px solid #d9d9d9",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 12, color: "#8c8c8c" }}>
          SQL 编辑器 — Ctrl+Enter 执行
        </span>
        <span style={{ fontSize: 12, color: "#bfbfbf" }}>
          T-SQL / PG / DM-SQL
        </span>
      </div>
      <Editor
        height="220px"
        language="sql"
        theme="vs-dark"
        onMount={handleMount}
        loading={<div style={{ padding: 24, textAlign: "center" }}>加载编辑器...</div>}
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: "on",
          scrollBeyondLastLine: false,
          wordWrap: "on",
          automaticLayout: true,
          tabSize: 2,
        }}
      />
    </div>
  );
}

import Editor, { type OnMount } from "@monaco-editor/react";
import type { editor } from "monaco-editor";
import { useRef } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onExecute: () => void;
}

export default function SqlEditor({ value, onChange, onExecute }: Props) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;

    // Ctrl/Cmd+Enter to execute
    editor.addAction({
      id: "execute-sql",
      label: "Execute SQL",
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
      run: () => onExecute(),
    });
  };

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
        value={value}
        onChange={(v) => onChange(v ?? "")}
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
          placeholder: "输入 SQL 语句...",
        }}
      />
    </div>
  );
}

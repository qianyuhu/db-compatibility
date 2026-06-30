/**
 * Custom React Flow nodes for CFG visualization.
 *
 * Each node type renders a different shape per CFG Rule 1:
 *   sql         → rectangle
 *   if          → diamond
 *   while       → loop circle
 *   exec        → call node (rounded rect)
 *   assign      → small rectangle
 *   return      → small rectangle
 *   transaction → rectangle
 *   variable    → rectangle
 *
 * Status colors (Rule 3):
 *   pending → #d9d9d9 gray
 *   running → #1677ff blue with CSS pulse
 *   success → #52c41a green
 *   failed  → #ff4d4f red
 *   skipped → #8c8c8c dark gray
 */

import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { UINode } from "../../api/cfgWorkbench";

// ---------------------------------------------------------------------------
// Status colors
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<string, string> = {
  pending: "#d9d9d9",
  running: "#1677ff",
  success: "#52c41a",
  failed: "#ff4d4f",
  skipped: "#8c8c8c",
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] || STATUS_COLORS.pending;
}

// ---------------------------------------------------------------------------
// SQL Node — rectangle
// ---------------------------------------------------------------------------

export function SqlNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);
  const isRunning = node.status === "running";

  return (
    <div
      style={{
        padding: "10px 14px",
        borderRadius: 6,
        border: `2px solid ${color}`,
        background: "#fff",
        minWidth: 140,
        maxWidth: 240,
        fontSize: 12,
        fontFamily: "monospace",
        boxShadow: `0 1px 4px ${color}33`,
        animation: isRunning ? "cfg-pulse 1s infinite ease-in-out" : undefined,
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ fontWeight: 600, color, marginBottom: 4 }}>SQL</div>
      <div style={{ color: "#333", lineHeight: 1.4, wordBreak: "break-word" }}>
        {node.label}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// IF Node — diamond shape
// ---------------------------------------------------------------------------

export function IfNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);
  const isRunning = node.status === "running";

  return (
    <div
      style={{
        width: 120,
        height: 80,
        transform: "rotate(0deg)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        position: "relative",
      }}
    >
      <div
        style={{
          width: 100,
          height: 70,
          transform: "rotate(45deg)",
          border: `2px solid ${color}`,
          background: "#fff",
          boxShadow: `0 1px 6px ${color}33`,
          animation: isRunning ? "cfg-pulse 1s infinite ease-in-out" : undefined,
          position: "absolute",
        }}
      />
      <div
        style={{
          position: "absolute",
          fontSize: 11,
          fontWeight: 600,
          color: "#333",
          textAlign: "center",
          maxWidth: 90,
          lineHeight: 1.3,
          wordBreak: "break-word",
        }}
      >
        <span style={{ color, fontSize: 10, display: "block" }}>IF</span>
        {node.label.replace(/^IF /, "")}
      </div>
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        style={{ background: "#52c41a", left: "30%" }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        style={{ background: "#ff4d4f", left: "70%" }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// WHILE Node — circle
// ---------------------------------------------------------------------------

export function WhileNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);
  const isRunning = node.status === "running";

  return (
    <div
      style={{
        width: 100,
        height: 100,
        borderRadius: "50%",
        border: `3px solid ${color}`,
        background: "#fff",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: `0 1px 6px ${color}33`,
        animation: isRunning ? "cfg-pulse 1s infinite ease-in-out" : undefined,
        position: "relative",
        fontSize: 11,
        padding: 8,
        textAlign: "center",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ fontWeight: 700, color, fontSize: 10, marginBottom: 2 }}>WHILE</div>
      <div style={{ color: "#333", lineHeight: 1.3, wordBreak: "break-word", maxWidth: 80 }}>
        {node.label.replace(/^WHILE /, "")}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        style={{ background: "#52c41a", left: "35%" }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        style={{ background: "#ff4d4f", left: "65%" }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// EXEC Node — rounded rectangle with call icon
// ---------------------------------------------------------------------------

export function ExecNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);

  return (
    <div
      style={{
        padding: "8px 14px",
        borderRadius: 20,
        border: `2px solid ${color}`,
        background: "#fff",
        minWidth: 120,
        fontSize: 12,
        fontFamily: "monospace",
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ fontWeight: 600, color, marginBottom: 2 }}>📞 EXEC</div>
      <div style={{ color: "#333" }}>{node.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ASSIGN Node — small rectangle
// ---------------------------------------------------------------------------

export function AssignNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);

  return (
    <div
      style={{
        padding: "6px 12px",
        borderRadius: 4,
        border: `1.5px solid ${color}`,
        background: "#fafafa",
        minWidth: 100,
        maxWidth: 200,
        fontSize: 11,
        fontFamily: "monospace",
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ color: "#555", wordBreak: "break-word" }}>{node.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// RETURN Node — small rectangle with return icon
// ---------------------------------------------------------------------------

export function ReturnNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);

  return (
    <div
      style={{
        padding: "6px 12px",
        borderRadius: 4,
        border: `2px solid ${color}`,
        background: "#fff0f0",
        minWidth: 80,
        fontSize: 11,
        fontFamily: "monospace",
        position: "relative",
        textAlign: "center",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ fontWeight: 600, color: "#ff4d4f" }}>⏎ {node.label}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default Node — used for variable, transaction, block types
// ---------------------------------------------------------------------------

export function DefaultNode({ data }: NodeProps) {
  const node = data as unknown as UINode;
  const color = statusColor(node.status);

  return (
    <div
      style={{
        padding: "8px 14px",
        borderRadius: 6,
        border: `1.5px solid ${color}`,
        background: "#fff",
        minWidth: 100,
        maxWidth: 220,
        fontSize: 12,
        fontFamily: "monospace",
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: color }} />
      <div style={{ fontWeight: 600, color, fontSize: 10, marginBottom: 2 }}>
        {node.type.toUpperCase()}
      </div>
      <div style={{ color: "#333", lineHeight: 1.3, wordBreak: "break-word" }}>{node.label}</div>
      <Handle type="source" position={Position.Bottom} style={{ background: color }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node type registry (for React Flow's nodeTypes prop)
// ---------------------------------------------------------------------------

export const cfgNodeTypes = {
  sql: SqlNode,
  if: IfNode,
  while: WhileNode,
  exec: ExecNode,
  assign: AssignNode,
  return: ReturnNode,
  transaction: DefaultNode,
  variable: DefaultNode,
  block: DefaultNode,
  procedure: DefaultNode,
};

/**
 * Custom React Flow edge for CFG visualization.
 *
 * Edge styles per Rule 2:
 *   sequential   → solid gray line
 *   true_branch  → green line with animated dash
 *   false_branch → red dashed line
 *   loop_back    → curved arrow (green)
 */

import {
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";

const EDGE_STYLES: Record<string, { stroke: string; dasharray?: string }> = {
  sequential:   { stroke: "#8c8c8c" },
  true_branch:  { stroke: "#52c41a", dasharray: "8 4" },
  false_branch: { stroke: "#ff4d4f", dasharray: "4 4" },
  loop_back:    { stroke: "#52c41a", dasharray: "8 4" },
};

export default function CfgEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  markerEnd,
}: EdgeProps) {
  const edgeType = (data?.edge_type as string) || "sequential";
  const style = EDGE_STYLES[edgeType] || EDGE_STYLES.sequential;
  const label = (data?.label as string) || "";

  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 8,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: style.stroke,
          strokeWidth: edgeType === "sequential" ? 1.5 : 2,
          strokeDasharray: style.dasharray,
          animation: edgeType === "true_branch" || edgeType === "loop_back"
            ? "cfg-edge-dash 0.5s linear infinite"
            : undefined,
        }}
        markerEnd={markerEnd}
      />
      {label && (
        <text
          x={labelX}
          y={labelY - 8}
          style={{
            fill: style.stroke,
            fontSize: 10,
            fontWeight: 600,
            fontFamily: "monospace",
          }}
          textAnchor="middle"
          dominantBaseline="middle"
        >
          {label}
        </text>
      )}
    </>
  );
}

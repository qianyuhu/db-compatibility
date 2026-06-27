/**
 * RadarChart — SVG-based radar/spider chart for 4-dimensional score visualization.
 *
 * Pure SVG implementation: no chart library dependency.
 * Renders syntax / execution / result / risk on 4 axes.
 */
import type { ScoreBreakdown } from "../api/sqlScore";

interface RadarChartProps {
  breakdown: ScoreBreakdown;
  score: number;
  size?: number;
}

const DIMENSIONS: (keyof ScoreBreakdown)[] = [
  "syntax",
  "execution",
  "result",
  "risk",
];

const DIM_LABELS: Record<string, string> = {
  syntax: "语法兼容\nSyntax",
  execution: "执行成功\nExecution",
  result: "结果一致\nResult",
  risk: "风险评估\nRisk",
};

const CENTER = 130;
const RADIUS = 100;
const VIEWBOX = 260;
const LEVELS = 5; // concentric rings (20, 40, 60, 80, 100)

export default function RadarChart({ breakdown, score, size = 300 }: RadarChartProps) {
  const dimCount = DIMENSIONS.length;
  const angleStep = (2 * Math.PI) / dimCount;
  const startAngle = -Math.PI / 2; // start from top

  // Calculate polygon points for a given set of values (0-100)
  const getPoints = (values: number[]): string => {
    return values
      .map((val, i) => {
        const angle = startAngle + i * angleStep;
        const r = (val / 100) * RADIUS;
        const x = CENTER + r * Math.cos(angle);
        const y = CENTER + r * Math.sin(angle);
        return `${x},${y}`;
      })
      .join(" ");
  };

  // Calculate grid rings
  const renderGrid = () => {
    const rings: React.ReactNode[] = [];
    for (let level = 1; level <= LEVELS; level++) {
      const r = (level / LEVELS) * RADIUS;
      const points = DIMENSIONS.map((_, i) => {
        const angle = startAngle + i * angleStep;
        const x = CENTER + r * Math.cos(angle);
        const y = CENTER + r * Math.sin(angle);
        return `${x},${y}`;
      }).join(" ");

      rings.push(
        <polygon
          key={`ring-${level}`}
          points={points}
          fill="none"
          stroke={level === LEVELS ? "#d9d9d9" : "#f0f0f0"}
          strokeWidth={level === LEVELS ? 1.5 : 1}
        />,
      );
    }
    return rings;
  };

  // Calculate axis lines
  const renderAxes = () => {
    return DIMENSIONS.map((_, i) => {
      const angle = startAngle + i * angleStep;
      const x = CENTER + RADIUS * Math.cos(angle);
      const y = CENTER + RADIUS * Math.sin(angle);
      return (
        <line
          key={`axis-${i}`}
          x1={CENTER}
          y1={CENTER}
          x2={x}
          y2={y}
          stroke="#e8e8e8"
          strokeWidth={1}
        />
      );
    });
  };

  // Calculate data polygon
  const dataPoints = DIMENSIONS.map((dim) => breakdown[dim]);
  const dataPolygon = getPoints(dataPoints);

  // Calculate labels
  const renderLabels = () => {
    return DIMENSIONS.map((dim, i) => {
      const angle = startAngle + i * angleStep;
      const labelR = RADIUS + 22;
      const x = CENTER + labelR * Math.cos(angle);
      const y = CENTER + labelR * Math.sin(angle);

      // Position adjustment for text-anchor
      const xRatio = Math.cos(angle);
      const anchor: "middle" | "start" | "end" =
        Math.abs(xRatio) < 0.1 ? "middle" : xRatio > 0 ? "start" : "end";

      const lines = (DIM_LABELS[dim] || dim).split("\n");

      return (
        <text
          key={`label-${i}`}
          x={x}
          y={y}
          textAnchor={anchor}
          dominantBaseline="middle"
          style={{ fontSize: 11, fill: "#595959", fontWeight: 500 }}
        >
          {lines.map((line, li) => (
            <tspan key={li} x={x} dy={li === 0 ? 0 : 14}>
              {line}
            </tspan>
          ))}
        </text>
      );
    });
  };

  const weightedScore = Math.round(score);

  return (
    <div style={{ display: "flex", justifyContent: "center" }}>
      <svg
        viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
        width={size}
        height={size}
        style={{ maxWidth: "100%" }}
      >
        {/* Grid */}
        {renderGrid()}

        {/* Axes */}
        {renderAxes()}

        {/* Data area */}
        <polygon
          points={dataPolygon}
          fill="rgba(22, 119, 255, 0.15)"
          stroke="#1677ff"
          strokeWidth={2}
          strokeLinejoin="round"
        />

        {/* Data points */}
        {DIMENSIONS.map((dim, i) => {
          const angle = startAngle + i * angleStep;
          const r = (breakdown[dim] / 100) * RADIUS;
          const x = CENTER + r * Math.cos(angle);
          const y = CENTER + r * Math.sin(angle);
          return (
            <circle
              key={`dot-${i}`}
              cx={x}
              cy={y}
              r={4}
              fill="#1677ff"
              stroke="#fff"
              strokeWidth={2}
            />
          );
        })}

        {/* Center score (weighted final score) */}
        <text
          x={CENTER}
          y={CENTER - 4}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: 20, fontWeight: 700, fill: "#1677ff" }}
        >
          {weightedScore}
        </text>
        <text
          x={CENTER}
          y={CENTER + 16}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{ fontSize: 10, fill: "#8c8c8c" }}
        >
          score
        </text>

        {/* Labels */}
        {renderLabels()}
      </svg>
    </div>
  );
}

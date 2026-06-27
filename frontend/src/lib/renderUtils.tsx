/**
 * Shared cell value renderer — used by ResultTable, SideBySideResult, DiffTable.
 *
 * Single rendering layer for null / boolean / date / binary / scalar
 * so all result visualizations stay consistent across components.
 */

import type { ReactNode } from "react";
import { Typography } from "antd";

export function renderCellValue(val: unknown): ReactNode {
  if (val === null) {
    return (
      <Typography.Text type="secondary" italic>
        (null)
      </Typography.Text>
    );
  }
  if (typeof val === "boolean") {
    return val ? "true" : "false";
  }
  return String(val);
}

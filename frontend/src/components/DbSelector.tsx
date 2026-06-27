import { Select, Tag } from "antd";

export type DbType = "mssql" | "kingbasees" | "dm8";

const DB_OPTIONS: { value: DbType; label: string; color: string; desc: string }[] = [
  {
    value: "mssql",
    label: "MSSQL",
    color: "#1677ff",
    desc: "SQL Server 2022 — pyodbc",
  },
  {
    value: "kingbasees",
    label: "KingbaseES",
    color: "#52c41a",
    desc: "人大金仓 MSSQL 兼容模式 — psycopg2",
  },
  {
    value: "dm8",
    label: "DM8",
    color: "#fa8c16",
    desc: "达梦 DM8 — dmPython",
  },
];

interface Props {
  value: DbType;
  onChange: (db: DbType) => void;
}

export default function DbSelector({ value, onChange }: Props) {
  const current = DB_OPTIONS.find((o) => o.value === value);

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
        目标数据库:
      </span>
      <Select
        value={value}
        onChange={onChange}
        style={{ width: 280 }}
        options={DB_OPTIONS.map((opt) => ({
          value: opt.value,
          label: (
            <span>
              <Tag color={opt.color} style={{ marginRight: 4 }}>
                {opt.label}
              </Tag>
              {opt.desc}
            </span>
          ),
        }))}
      />
      {current && <Tag color={current.color}>{current.label}</Tag>}
    </div>
  );
}

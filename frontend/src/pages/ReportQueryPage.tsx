import { useState } from "react";
import {
  Card,
  Button,
  Select,
  Typography,
  Tag,
  Alert,
  Row,
  Col,
  Spin,
  Space,
  DatePicker,
  Input,
  message,
  Tabs,
} from "antd";
import {
  BarChartOutlined,
  PieChartOutlined,
  TeamOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import GeneratedSqlPanel from "../components/GeneratedSqlPanel";
import SideBySideResult from "../components/SideBySideResult";
import {
  runSalesReport,
  runInventoryReport,
  runCustomerOrderReport,
  type BusinessOperationResponse,
} from "../api/business";

type ReportTab = "sales" | "inventory" | "customer";

export default function ReportQueryPage() {
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BusinessOperationResponse | null>(null);
  const [activeReport, setActiveReport] = useState<ReportTab>("sales");

  // Sales report params
  const [salesDateFrom, setSalesDateFrom] = useState<string | null>(null);
  const [salesDateTo, setSalesDateTo] = useState<string | null>(null);

  // Inventory report params
  const [invWarehouse, setInvWarehouse] = useState<string>("");

  // Customer report params
  const [custCode, setCustCode] = useState<string>("");

  const runReport = async () => {
    setLoading(true);
    setResult(null);
    try {
      let res: BusinessOperationResponse;
      switch (activeReport) {
        case "sales":
          res = await runSalesReport({
            date_from: salesDateFrom,
            date_to: salesDateTo,
            source_db: sourceDb,
            target_db: targetDb,
          });
          break;
        case "inventory":
          res = await runInventoryReport({
            warehouse: invWarehouse || null,
            source_db: sourceDb,
            target_db: targetDb,
          });
          break;
        case "customer":
          res = await runCustomerOrderReport({
            customer_code: custCode || null,
            source_db: sourceDb,
            target_db: targetDb,
          });
          break;
      }
      setResult(res);
      if (res.equal) {
        message.success("报表查询完成，双库结果一致 ✅");
      } else {
        message.warning("报表查询完成，双库结果存在差异 ⚠️");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`查询失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <BarChartOutlined /> Complex Report Queries
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        复杂报表查询 — 验证 JOIN + GROUP BY + 聚合函数的跨数据库兼容性
      </Typography.Paragraph>

      {/* DB Selector */}
      <Space style={{ marginBottom: 16 }}>
        <Select value={sourceDb} onChange={setSourceDb} style={{ width: 140 }}>
          <Select.Option value="mssql">源库: MSSQL</Select.Option>
          <Select.Option value="kingbasees">源库: KingbaseES</Select.Option>
          <Select.Option value="dm8">源库: DM8</Select.Option>
        </Select>
        <Typography.Text type="secondary">→</Typography.Text>
        <Select value={targetDb} onChange={setTargetDb} style={{ width: 160 }}>
          <Select.Option value="kingbasees">目标库: KingbaseES</Select.Option>
          <Select.Option value="dm8">目标库: DM8</Select.Option>
          <Select.Option value="mssql">目标库: MSSQL</Select.Option>
        </Select>
      </Space>

      {/* Report Type Tabs */}
      <Card style={{ marginBottom: 24 }}>
        <Tabs
          activeKey={activeReport}
          onChange={(key) => {
            setActiveReport(key as ReportTab);
            setResult(null);
          }}
          items={[
            {
              key: "sales",
              label: (
                <span>
                  <BarChartOutlined /> 销售聚合报表
                </span>
              ),
            },
            {
              key: "inventory",
              label: (
                <span>
                  <PieChartOutlined /> 库存汇总报表
                </span>
              ),
            },
            {
              key: "customer",
              label: (
                <span>
                  <TeamOutlined /> 客户订单汇总
                </span>
              ),
            },
          ]}
        />

        {/* Report Parameters */}
        <Space wrap style={{ marginTop: 16 }}>
          {activeReport === "sales" && (
            <>
              <DatePicker.RangePicker
                placeholder={["开始日期", "结束日期"]}
                onChange={(dates) => {
                  if (dates && dates[0] && dates[1]) {
                    setSalesDateFrom(dates[0].format("YYYY-MM-DD"));
                    setSalesDateTo(dates[1].format("YYYY-MM-DD"));
                  } else {
                    setSalesDateFrom(null);
                    setSalesDateTo(null);
                  }
                }}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                JOIN: order_items + orders + products | GROUP BY: product | SUM: quantity × price
              </Typography.Text>
            </>
          )}
          {activeReport === "inventory" && (
            <>
              <Input
                placeholder="仓库编码（可选）"
                value={invWarehouse}
                onChange={(e) => setInvWarehouse(e.target.value)}
                style={{ width: 160 }}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                JOIN: inventory + products | GROUP BY: warehouse | AVG, MIN, MAX, SUM
              </Typography.Text>
            </>
          )}
          {activeReport === "customer" && (
            <>
              <Input
                placeholder="客户编码（可选）"
                value={custCode}
                onChange={(e) => setCustCode(e.target.value)}
                style={{ width: 160 }}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                JOIN: customers + orders (LEFT) | GROUP BY: customer | COUNT, SUM, AVG
              </Typography.Text>
            </>
          )}

          <Button
            type="primary"
            icon={<BarChartOutlined />}
            loading={loading}
            onClick={runReport}
          >
            执行报表
          </Button>
        </Space>
      </Card>

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin size="large" description="报表查询执行中..." />
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <>
          <GeneratedSqlPanel
            sourceSql={result.generated_sql_source}
            targetSql={result.generated_sql_target}
            sourceDb={sourceDb}
            targetDb={targetDb}
          />

          <Alert
            type={result.equal ? "success" : "warning"}
            title={
              result.equal ? (
                <span><CheckCircleOutlined /> 双库报表结果一致</span>
              ) : (
                <span>
                  <CloseCircleOutlined /> 双库报表结果存在 {result.diff_detail.length} 处差异
                </span>
              )
            }
            description={
              result.equal
                ? `源库(${sourceDb})和目标库(${targetDb})返回完全一致的聚合结果`
                : `请查看下方详细对比`
            }
            style={{ marginBottom: 16 }}
            showIcon={false}
          />

          <Row gutter={16}>
            <Col span={12}>
              <Card
                title={<Tag color="blue">{sourceDb.toUpperCase()} (源库)</Tag>}
                size="small"
              >
                <SideBySideResult
                  dbLabel={sourceDb}
                  color="blue"
                  result={result.source_result.success ? result.source_result : undefined}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card
                title={<Tag color="green">{targetDb.toUpperCase()} (目标库)</Tag>}
                size="small"
              >
                <SideBySideResult
                  dbLabel={targetDb}
                  color="green"
                  result={result.target_result.success ? result.target_result : undefined}
                />
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}

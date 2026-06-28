import { useState } from "react";
import {
  Card,
  Form,
  Input,
  InputNumber,
  Button,
  Select,
  Tag,
  Typography,
  Alert,
  Row,
  Col,
  Divider,
  Spin,
  Space,
  message,
  Descriptions,
} from "antd";
import {
  BarcodeOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
} from "@ant-design/icons";
import GeneratedSqlPanel from "../components/GeneratedSqlPanel";
import SideBySideResult from "../components/SideBySideResult";
import {
  queryStock,
  adjustStock,
  type BusinessOperationResponse,
} from "../api/business";

export default function InventoryQuery() {
  const [queryForm] = Form.useForm();
  const [adjustForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [queryResult, setQueryResult] = useState<BusinessOperationResponse | null>(null);
  const [adjustResult, setAdjustResult] = useState<BusinessOperationResponse | null>(null);
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");

  const handleQuery = async (values: { product_code: string }) => {
    setLoading(true);
    setQueryResult(null);
    try {
      const res = await queryStock({
        product_code: values.product_code,
        source_db: sourceDb,
        target_db: targetDb,
      });
      setQueryResult(res);
      message.success("库存查询完成");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`查询失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAdjust = async (values: { product_code: string; delta: number; reason?: string }) => {
    setLoading(true);
    setAdjustResult(null);
    try {
      const res = await adjustStock({
        product_code: values.product_code,
        delta: values.delta,
        reason: values.reason,
        source_db: sourceDb,
        target_db: targetDb,
      });
      setAdjustResult(res);
      if (res.equal) {
        message.success("库存调整完成，双库结果一致 ✅");
      } else {
        message.warning("库存调整完成，但双库结果存在差异 ⚠️");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`调整失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <BarcodeOutlined /> Inventory Query
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        查询和调整产品库存，实时对比双库数据
      </Typography.Paragraph>

      {/* SQL Coverage Indicators */}
      <div style={{ marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Tag color="green">JOIN ✔</Tag>
        <Tag color="green">GROUP BY ✔</Tag>
        <Tag color="green">UPSERT ✔</Tag>
        <Tag color="green">TRANSACTION ✔</Tag>
        <Tag color="blue">SELECT ✔</Tag>
        <Tag color="blue">UPDATE ✔</Tag>
      </div>

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

      {/* Stock Query */}
      <Card title="库存查询" style={{ marginBottom: 24 }}>
        <Form
          form={queryForm}
          layout="inline"
          onFinish={handleQuery}
        >
          <Form.Item
            label="产品编码"
            name="product_code"
            rules={[{ required: true, message: "请输入产品编码" }]}
          >
            <Input placeholder="例如: P001" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<BarcodeOutlined />}
            >
              查询库存
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {/* Query Results */}
      {queryResult && (
        <Card title="查询结果" size="small" style={{ marginBottom: 24 }}>
          <GeneratedSqlPanel
            sourceSql={queryResult.generated_sql_source}
            targetSql={queryResult.generated_sql_target}
            sourceDb={sourceDb}
            targetDb={targetDb}
          />

          <Alert
            type={queryResult.equal ? "success" : "warning"}
            message={
              queryResult.equal ? (
                <span><CheckCircleOutlined /> 双库库存数据一致</span>
              ) : (
                <span><CloseCircleOutlined /> 双库库存数据不一致</span>
              )
            }
            style={{ marginBottom: 16 }}
            showIcon={false}
          />

          <Row gutter={16}>
            <Col span={12}>
              <Card title={<Tag color="blue">{sourceDb.toUpperCase()} (源库)</Tag>} size="small">
                <SideBySideResult
                  dbLabel={sourceDb}
                  color="blue"
                  result={queryResult.source_result.success ? queryResult.source_result : undefined}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card title={<Tag color="green">{targetDb.toUpperCase()} (目标库)</Tag>} size="small">
                <SideBySideResult
                  dbLabel={targetDb}
                  color="green"
                  result={queryResult.target_result.success ? queryResult.target_result : undefined}
                />
              </Card>
            </Col>
          </Row>
        </Card>
      )}

      {/* Consistency Check Panel */}
      {queryResult && (
        <Card
          title={
            <span>
              <CheckCircleOutlined
                style={{ color: queryResult.equal ? "#52c41a" : "#ff4d4f", marginRight: 8 }}
              />
              一致性检查面板
            </span>
          }
          size="small"
          style={{ marginBottom: 24 }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Card size="small" title="MSSQL 结果" bordered>
                <Typography.Text>
                  行数: <strong>{queryResult.source_result.row_count}</strong>
                </Typography.Text>
                <br />
                <Typography.Text>
                  执行时间: <strong>{queryResult.source_result.execution_time_ms}ms</strong>
                </Typography.Text>
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title="KingbaseES 结果" bordered>
                <Typography.Text>
                  行数: <strong>{queryResult.target_result.row_count}</strong>
                </Typography.Text>
                <br />
                <Typography.Text>
                  执行时间: <strong>{queryResult.target_result.execution_time_ms}ms</strong>
                </Typography.Text>
              </Card>
            </Col>
          </Row>

          {!queryResult.equal && queryResult.diff_detail.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <Typography.Text strong type="danger">
                差异明细 ({queryResult.diff_detail.length} 处):
              </Typography.Text>
              {queryResult.diff_detail.map((diff, i) => (
                <Alert
                  key={i}
                  type="warning"
                  message={
                    <span>
                      <strong>{diff.field}:</strong>{" "}
                      <span style={{ color: "#1677ff" }}>
                        MSSQL={JSON.stringify(diff.source)}
                      </span>
                      {" ≠ "}
                      <span style={{ color: "#52c41a" }}>
                        KingbaseES={JSON.stringify(diff.target)}
                      </span>
                    </span>
                  }
                  style={{ marginTop: 8 }}
                  showIcon={false}
                />
              ))}
            </div>
          )}

          {queryResult.equal && (
            <Alert
              type="success"
              message="数据完全一致 — MSSQL 和 KingbaseES 返回相同结果"
              style={{ marginTop: 12 }}
              showIcon={false}
            />
          )}
        </Card>
      )}

      <Divider />

      {/* Stock Adjustment */}
      <Card title="库存调整" style={{ marginBottom: 24 }}>
        <Form
          form={adjustForm}
          layout="vertical"
          onFinish={handleAdjust}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                label="产品编码"
                name="product_code"
                rules={[{ required: true, message: "请输入产品编码" }]}
              >
                <Input placeholder="例如: P001" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                label="变动量"
                name="delta"
                rules={[{ required: true, message: "请输入变动量" }]}
              >
                <InputNumber
                  placeholder="正数=入库，负数=出库"
                  style={{ width: "100%" }}
                  prefix={undefined}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="原因" name="reason">
                <Input placeholder="调整原因（可选）" />
              </Form.Item>
            </Col>
          </Row>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            icon={<ArrowUpOutlined />}
          >
            调整库存
          </Button>
        </Form>
      </Card>

      {/* Adjust Results */}
      {adjustResult && (
        <Card title="调整结果" size="small" style={{ marginBottom: 24 }}>
          <GeneratedSqlPanel
            sourceSql={adjustResult.generated_sql_source}
            targetSql={adjustResult.generated_sql_target}
            sourceDb={sourceDb}
            targetDb={targetDb}
          />

          <Alert
            type={adjustResult.equal ? "success" : "warning"}
            message={
              adjustResult.equal ? (
                <span><CheckCircleOutlined /> 双库调整一致</span>
              ) : (
                <span><CloseCircleOutlined /> 双库调整存在 {adjustResult.diff_detail.length} 处差异</span>
              )
            }
            style={{ marginBottom: 16 }}
            showIcon={false}
          />

          <Row gutter={16}>
            <Col span={12}>
              <Card title={<Tag color="blue">{sourceDb.toUpperCase()} (源库)</Tag>} size="small">
                <SideBySideResult
                  dbLabel={sourceDb}
                  color="blue"
                  result={adjustResult.source_result.success ? adjustResult.source_result : undefined}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card title={<Tag color="green">{targetDb.toUpperCase()} (目标库)</Tag>} size="small">
                <SideBySideResult
                  dbLabel={targetDb}
                  color="green"
                  result={adjustResult.target_result.success ? adjustResult.target_result : undefined}
                />
              </Card>
            </Col>
          </Row>
        </Card>
      )}

      {loading && (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin size="large" />
        </div>
      )}
    </div>
  );
}

import { useState } from "react";
import {
  Card,
  Form,
  Input,
  InputNumber,
  Button,
  Select,
  Space,
  Tag,
  Typography,
  Alert,
  Row,
  Col,
  Divider,
  Spin,
  message,
} from "antd";
import {
  ShoppingCartOutlined,
  PlusOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import GeneratedSqlPanel from "../components/GeneratedSqlPanel";
import SideBySideResult from "../components/SideBySideResult";
import {
  createOrder,
  type OrderItemInput,
  type BusinessOperationResponse,
} from "../api/business";

interface LineItem extends OrderItemInput {
  key: string;
}

let itemKeyCounter = 0;

export default function OrderManagement() {
  const [form] = Form.useForm();
  const [items, setItems] = useState<LineItem[]>([
    { key: `item-${itemKeyCounter++}`, product_code: "", quantity: 1, unit_price: 0 },
  ]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BusinessOperationResponse | null>(null);
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");

  const addItem = () => {
    setItems((prev) => [
      ...prev,
      { key: `item-${itemKeyCounter++}`, product_code: "", quantity: 1, unit_price: 0 },
    ]);
  };

  const removeItem = (key: string) => {
    if (items.length <= 1) return;
    setItems((prev) => prev.filter((i) => i.key !== key));
  };

  const updateItem = (key: string, field: keyof LineItem, value: string | number) => {
    setItems((prev) =>
      prev.map((i) => (i.key === key ? { ...i, [field]: value } : i)),
    );
  };

  const handleSubmit = async (values: { customer_code: string; notes?: string }) => {
    const orderItems = items.map(({ product_code, quantity, unit_price }) => ({
      product_code,
      quantity,
      unit_price,
    }));

    setLoading(true);
    setResult(null);
    try {
      const res = await createOrder({
        customer_code: values.customer_code,
        items: orderItems,
        notes: values.notes,
        source_db: sourceDb,
        target_db: targetDb,
      });
      setResult(res);
      if (res.equal) {
        message.success("订单创建成功，双库结果一致 ✅");
      } else {
        message.warning("订单创建完成，但双库结果存在差异 ⚠️");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`创建失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const totalAmount = items.reduce(
    (sum, item) => sum + item.quantity * item.unit_price,
    0,
  );

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <ShoppingCartOutlined /> Order Management
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        创建订单，系统自动生成 SQL 并在源库和目标库执行对比
      </Typography.Paragraph>

      {/* SQL Coverage Indicators */}
      <div style={{ marginBottom: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Tag color="green">JOIN ✔</Tag>
        <Tag color="green">GROUP BY ✔</Tag>
        <Tag color="green">TRANSACTION ✔</Tag>
        <Tag color="green">INDEX FILTER ✔</Tag>
        <Tag color="blue">INSERT ✔</Tag>
        <Tag color="blue">SELECT ✔</Tag>
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

      {/* Order Form */}
      <Card style={{ marginBottom: 24 }}>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{ customer_code: "", notes: "" }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                label="客户编码"
                name="customer_code"
                rules={[{ required: true, message: "请输入客户编码" }]}
              >
                <Input placeholder="例如: C001" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="备注" name="notes">
                <Input placeholder="订单备注（可选）" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="订单总额">
                <Input
                  value={`¥${totalAmount.toFixed(2)}`}
                  disabled
                  style={{ fontWeight: 600, color: "#1677ff" }}
                />
              </Form.Item>
            </Col>
          </Row>

          {/* Line Items */}
          <Typography.Text strong style={{ display: "block", marginBottom: 8 }}>
            订单行项目
          </Typography.Text>
          {items.map((item) => (
            <Row key={item.key} gutter={8} style={{ marginBottom: 8 }}>
              <Col span={6}>
                <Input
                  placeholder="产品编码"
                  value={item.product_code}
                  onChange={(e) => updateItem(item.key, "product_code", e.target.value)}
                />
              </Col>
              <Col span={4}>
                <InputNumber
                  placeholder="数量"
                  min={1}
                  value={item.quantity}
                  onChange={(v) => updateItem(item.key, "quantity", v ?? 1)}
                  style={{ width: "100%" }}
                />
              </Col>
              <Col span={4}>
                <InputNumber
                  placeholder="单价"
                  min={0}
                  step={0.01}
                  value={item.unit_price}
                  onChange={(v) => updateItem(item.key, "unit_price", v ?? 0)}
                  style={{ width: "100%" }}
                  prefix="¥"
                />
              </Col>
              <Col span={4}>
                <Input
                  value={`¥${(item.quantity * item.unit_price).toFixed(2)}`}
                  disabled
                />
              </Col>
              <Col span={6}>
                <Space>
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => removeItem(item.key)}
                    disabled={items.length <= 1}
                  />
                </Space>
              </Col>
            </Row>
          ))}

          <Button
            type="dashed"
            onClick={addItem}
            icon={<PlusOutlined />}
            style={{ marginBottom: 16 }}
          >
            添加产品
          </Button>

          <Divider />

          <Button
            type="primary"
            htmlType="submit"
            loading={loading}
            icon={<ShoppingCartOutlined />}
            size="large"
          >
            创建订单
          </Button>
        </Form>
      </Card>

      {/* Results */}
      {loading && (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin size="large" description="正在创建订单并执行对比..." />
        </div>
      )}

      {result && !loading && (
        <>
          {/* Generated SQL */}
          <GeneratedSqlPanel
            sourceSql={result.generated_sql_source}
            targetSql={result.generated_sql_target}
            sourceDb={sourceDb}
            targetDb={targetDb}
          />

          {/* Match Status */}
          <Alert
            type={result.equal ? "success" : "warning"}
            message={
              result.equal ? (
                <span>
                  <CheckCircleOutlined /> 双库执行结果一致
                </span>
              ) : (
                <span>
                  <CloseCircleOutlined /> 双库执行结果存在 {result.diff_detail.length} 处差异
                </span>
              )
            }
            description={
              result.equal
                ? `源库(${sourceDb})和目标库(${targetDb})返回完全一致的结果`
                : `请查看下方详细对比`
            }
            style={{ marginBottom: 16 }}
            showIcon={false}
          />

          {/* Side-by-side Results */}
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
                {!result.source_result.success && (
                  <Alert
                    type="error"
                    message={result.source_result.error}
                    style={{ marginTop: 8 }}
                  />
                )}
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
                {!result.target_result.success && (
                  <Alert
                    type="error"
                    message={result.target_result.error}
                    style={{ marginTop: 8 }}
                  />
                )}
              </Card>
            </Col>
          </Row>

          {/* Kernel Analysis */}
          {result.kernel_analysis && (
            <Card title="SQLKernel 分析" size="small" style={{ marginTop: 16 }}>
              <Typography.Paragraph>
                兼容性分数: {String((result.kernel_analysis as Record<string, unknown>).score || "N/A")}
              </Typography.Paragraph>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                执行时间: {result.execution_time_ms}ms
              </Typography.Paragraph>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

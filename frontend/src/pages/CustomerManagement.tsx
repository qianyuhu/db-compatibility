import { useState } from "react";
import {
  Card,
  Form,
  Input,
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
  Switch,
} from "antd";
import {
  TeamOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SearchOutlined,
  UserAddOutlined,
} from "@ant-design/icons";
import GeneratedSqlPanel from "../components/GeneratedSqlPanel";
import SideBySideResult from "../components/SideBySideResult";
import {
  listCustomers,
  createCustomer,
  type BusinessOperationResponse,
} from "../api/business";

export default function CustomerManagement() {
  const [createForm] = Form.useForm();
  const [searchForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [searchResult, setSearchResult] = useState<BusinessOperationResponse | null>(null);
  const [createResult, setCreateResult] = useState<BusinessOperationResponse | null>(null);
  const [sourceDb, setSourceDb] = useState("mssql");
  const [targetDb, setTargetDb] = useState("kingbasees");
  const [activeMode, setActiveMode] = useState<"list" | "create">("list");

  const handleSearch = async (values: { code?: string; name?: string }) => {
    setLoading(true);
    setSearchResult(null);
    try {
      const res = await listCustomers({
        code: values.code || null,
        name: values.name || null,
        source_db: sourceDb,
        target_db: targetDb,
      });
      setSearchResult(res);
      const rowCount = res.source_result?.row_count ?? 0;
      message.success(`查询完成，找到 ${rowCount} 条客户记录`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`查询失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (values: {
    code: string;
    name: string;
    contact?: string;
    phone?: string;
    email?: string;
    is_active: boolean;
  }) => {
    setLoading(true);
    setCreateResult(null);
    try {
      const res = await createCustomer({
        code: values.code,
        name: values.name,
        contact: values.contact || null,
        phone: values.phone || null,
        email: values.email || null,
        is_active: values.is_active,
        source_db: sourceDb,
        target_db: targetDb,
      });
      setCreateResult(res);
      if (res.equal) {
        message.success("客户创建成功，双库结果一致 ✅");
      } else {
        message.warning("客户创建完成，但双库结果存在差异 ⚠️");
      }
      createForm.resetFields();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      message.error(`创建失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Typography.Title level={4}>
        <TeamOutlined /> Customer Management
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        客户主数据管理：查询、创建客户，双库执行对比验证
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

      {/* Mode Switch */}
      <Space style={{ marginBottom: 16 }}>
        <Button
          type={activeMode === "list" ? "primary" : "default"}
          icon={<SearchOutlined />}
          onClick={() => setActiveMode("list")}
        >
          查询客户
        </Button>
        <Button
          type={activeMode === "create" ? "primary" : "default"}
          icon={<UserAddOutlined />}
          onClick={() => setActiveMode("create")}
        >
          创建客户
        </Button>
      </Space>

      {/* Search Form */}
      {activeMode === "list" && (
        <Card style={{ marginBottom: 24 }}>
          <Form
            form={searchForm}
            layout="inline"
            onFinish={handleSearch}
          >
            <Form.Item label="客户编码" name="code">
              <Input placeholder="例如: C001" style={{ width: 160 }} />
            </Form.Item>
            <Form.Item label="客户名称" name="name">
              <Input placeholder="模糊搜索" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                icon={<SearchOutlined />}
              >
                查询
              </Button>
            </Form.Item>
          </Form>
        </Card>
      )}

      {/* Create Form */}
      {activeMode === "create" && (
        <Card title="新建客户" style={{ marginBottom: 24 }}>
          <Form
            form={createForm}
            layout="vertical"
            onFinish={handleCreate}
            initialValues={{ is_active: true }}
          >
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item
                  label="客户编码"
                  name="code"
                  rules={[{ required: true, message: "请输入客户编码" }]}
                >
                  <Input placeholder="例如: C001" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  label="客户名称"
                  name="name"
                  rules={[{ required: true, message: "请输入客户名称" }]}
                >
                  <Input placeholder="客户全称" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item label="启用状态" name="is_active" valuePropName="checked">
                  <Switch checkedChildren="启用" unCheckedChildren="停用" />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={8}>
                <Form.Item label="联系人" name="contact">
                  <Input placeholder="联系人姓名" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item label="电话" name="phone">
                  <Input placeholder="联系电话" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item label="邮箱" name="email">
                  <Input placeholder="电子邮箱" />
                </Form.Item>
              </Col>
            </Row>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<UserAddOutlined />}
              size="large"
            >
              创建客户
            </Button>
          </Form>
        </Card>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ textAlign: "center", padding: 40 }}>
          <Spin size="large" />
        </div>
      )}

      {/* Search Results */}
      {searchResult && !loading && (
        <Card title="查询结果" size="small" style={{ marginBottom: 24 }}>
          <GeneratedSqlPanel
            sourceSql={searchResult.generated_sql_source}
            targetSql={searchResult.generated_sql_target}
            sourceDb={sourceDb}
            targetDb={targetDb}
          />

          <Alert
            type={searchResult.equal ? "success" : "warning"}
            message={
              searchResult.equal ? (
                <span><CheckCircleOutlined /> 双库数据一致</span>
              ) : (
                <span><CloseCircleOutlined /> 双库数据存在 {searchResult.diff_detail.length} 处差异</span>
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
                  result={searchResult.source_result.success ? searchResult.source_result : undefined}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card title={<Tag color="green">{targetDb.toUpperCase()} (目标库)</Tag>} size="small">
                <SideBySideResult
                  dbLabel={targetDb}
                  color="green"
                  result={searchResult.target_result.success ? searchResult.target_result : undefined}
                />
              </Card>
            </Col>
          </Row>
        </Card>
      )}

      {/* Create Results */}
      {createResult && !loading && (
        <Card title="创建结果" size="small" style={{ marginBottom: 24 }}>
          <GeneratedSqlPanel
            sourceSql={createResult.generated_sql_source}
            targetSql={createResult.generated_sql_target}
            sourceDb={sourceDb}
            targetDb={targetDb}
          />

          <Alert
            type={createResult.equal ? "success" : "warning"}
            message={
              createResult.equal ? (
                <span><CheckCircleOutlined /> 双库创建一致</span>
              ) : (
                <span><CloseCircleOutlined /> 双库创建存在差异</span>
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
                  result={createResult.source_result.success ? createResult.source_result : undefined}
                />
              </Card>
            </Col>
            <Col span={12}>
              <Card title={<Tag color="green">{targetDb.toUpperCase()} (目标库)</Tag>} size="small">
                <SideBySideResult
                  dbLabel={targetDb}
                  color="green"
                  result={createResult.target_result.success ? createResult.target_result : undefined}
                />
              </Card>
            </Col>
          </Row>
        </Card>
      )}
    </div>
  );
}

import { useState, useCallback } from "react";
import { ConfigProvider, App as AntApp, theme, Tabs } from "antd";
import {
  CodeOutlined,
  SwapOutlined,
  ExperimentOutlined,
  ThunderboltOutlined,
  BugOutlined,
  RocketOutlined,
  PlayCircleOutlined,
  DashboardOutlined,
  ShoppingCartOutlined,
  BarcodeOutlined,
  DeploymentUnitOutlined,
  TeamOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  EyeOutlined,
  ApartmentOutlined,
} from "@ant-design/icons";
import zhCN from "antd/locale/zh_CN";
import SqlConsole from "./pages/SqlConsole";
import SqlCompare from "./pages/SqlCompare";
import SqlScore from "./pages/SqlScore";
import SqlRewrite from "./pages/SqlRewrite";
import SqlDiagnostics from "./pages/SqlDiagnostics";
import SqlMigrationPlan from "./pages/SqlMigrationPlan";
import SqlSimulation from "./pages/SqlSimulation";
import SqlKernel from "./pages/SqlKernel";
import OrderManagement from "./pages/OrderManagement";
import InventoryQuery from "./pages/InventoryQuery";
import MigrationDashboard from "./pages/MigrationDashboard";
import CustomerManagement from "./pages/CustomerManagement";
import ProductManagement from "./pages/ProductManagement";
import SQLCoverageDashboard from "./pages/SQLCoverageDashboard";
import ReportQueryPage from "./pages/ReportQueryPage";
import Showcase from "./pages/Showcase";
import CfgWorkbench from "./pages/CfgWorkbench";

type TabKey = "console" | "compare" | "score" | "rewrite" | "diagnostics" | "migration" | "simulation" | "kernel" | "orders" | "inventory" | "erp-migration" | "customers" | "products" | "coverage" | "reports" | "showcase" | "cfg-workbench";

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("console");

  const handleTabChange = useCallback((key: string) => {
    setActiveTab(key as TabKey);
  }, []);

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#1677ff",
          borderRadius: 6,
        },
      }}
    >
      <AntApp>
        <div
          style={{
            borderBottom: "1px solid #e8e8e8",
            background: "#fff",
            padding: "0 24px",
          }}
        >
          <Tabs
            activeKey={activeTab}
            onChange={handleTabChange}
            style={{ marginBottom: 0 }}
            items={[
              {
                key: "console",
                label: (
                  <span>
                    <CodeOutlined />
                    Console
                  </span>
                ),
              },
              {
                key: "compare",
                label: (
                  <span>
                    <SwapOutlined />
                    Compare
                  </span>
                ),
              },
              {
                key: "score",
                label: (
                  <span>
                    <ExperimentOutlined />
                    Score
                  </span>
                ),
              },
              {
                key: "rewrite",
                label: (
                  <span>
                    <ThunderboltOutlined />
                    Rewrite
                  </span>
                ),
              },
              {
                key: "diagnostics",
                label: (
                  <span>
                    <BugOutlined />
                    Diagnostics
                  </span>
                ),
              },
              {
                key: "migration",
                label: (
                  <span>
                    <RocketOutlined />
                    Migration
                  </span>
                ),
              },
              {
                key: "simulation",
                label: (
                  <span>
                    <PlayCircleOutlined />
                    Simulation
                  </span>
                ),
              },
              {
                key: "kernel",
                label: (
                  <span>
                    <DashboardOutlined />
                    Kernel
                  </span>
                ),
              },
              {
                key: "products",
                label: (
                  <span>
                    <AppstoreOutlined />
                    Products
                  </span>
                ),
              },
              {
                key: "customers",
                label: (
                  <span>
                    <TeamOutlined />
                    Customers
                  </span>
                ),
              },
              {
                key: "orders",
                label: (
                  <span>
                    <ShoppingCartOutlined />
                    Orders
                  </span>
                ),
              },
              {
                key: "inventory",
                label: (
                  <span>
                    <BarcodeOutlined />
                    Inventory
                  </span>
                ),
              },
              {
                key: "reports",
                label: (
                  <span>
                    <BarChartOutlined />
                    Reports
                  </span>
                ),
              },
              {
                key: "coverage",
                label: (
                  <span>
                    <DashboardOutlined />
                    Coverage
                  </span>
                ),
              },
              {
                key: "erp-migration",
                label: (
                  <span>
                    <DeploymentUnitOutlined />
                    ERP Migration
                  </span>
                ),
              },
              {
                key: "showcase",
                label: (
                  <span>
                    <EyeOutlined />
                    场景展示
                  </span>
                ),
              },
              {
                key: "cfg-workbench",
                label: (
                  <span>
                    <ApartmentOutlined />
                    CFG Workbench
                  </span>
                ),
              },
            ]}
          />
        </div>

        {/* Keep both pages mounted — prevent SQL/results loss on tab switch */}
        <div style={{ display: activeTab === "console" ? "block" : "none" }}>
          <SqlConsole />
        </div>
        <div style={{ display: activeTab === "compare" ? "block" : "none" }}>
          <SqlCompare />
        </div>
        <div style={{ display: activeTab === "score" ? "block" : "none" }}>
          <SqlScore />
        </div>
        <div style={{ display: activeTab === "rewrite" ? "block" : "none" }}>
          <SqlRewrite />
        </div>
        <div style={{ display: activeTab === "diagnostics" ? "block" : "none" }}>
          <SqlDiagnostics />
        </div>
        <div style={{ display: activeTab === "migration" ? "block" : "none" }}>
          <SqlMigrationPlan />
        </div>
        <div style={{ display: activeTab === "simulation" ? "block" : "none" }}>
          <SqlSimulation />
        </div>
        <div style={{ display: activeTab === "kernel" ? "block" : "none" }}>
          <SqlKernel />
        </div>
        <div style={{ display: activeTab === "orders" ? "block" : "none" }}>
          <OrderManagement />
        </div>
        <div style={{ display: activeTab === "inventory" ? "block" : "none" }}>
          <InventoryQuery />
        </div>
        <div style={{ display: activeTab === "erp-migration" ? "block" : "none" }}>
          <MigrationDashboard />
        </div>
        <div style={{ display: activeTab === "customers" ? "block" : "none" }}>
          <CustomerManagement />
        </div>
        <div style={{ display: activeTab === "products" ? "block" : "none" }}>
          <ProductManagement />
        </div>
        <div style={{ display: activeTab === "coverage" ? "block" : "none" }}>
          <SQLCoverageDashboard />
        </div>
        <div style={{ display: activeTab === "reports" ? "block" : "none" }}>
          <ReportQueryPage />
        </div>
        <div style={{ display: activeTab === "showcase" ? "block" : "none" }}>
          <Showcase />
        </div>
        <div style={{ display: activeTab === "cfg-workbench" ? "block" : "none" }}>
          <CfgWorkbench />
        </div>
      </AntApp>
    </ConfigProvider>
  );
}

import { useState, useCallback } from "react";
import { ConfigProvider, App as AntApp, theme, Tabs } from "antd";
import {
  CodeOutlined,
  SwapOutlined,
  ExperimentOutlined,
} from "@ant-design/icons";
import zhCN from "antd/locale/zh_CN";
import SqlConsole from "./pages/SqlConsole";
import SqlCompare from "./pages/SqlCompare";
import SqlScore from "./pages/SqlScore";

type TabKey = "console" | "compare" | "score";

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
                    SQL Console
                  </span>
                ),
              },
              {
                key: "compare",
                label: (
                  <span>
                    <SwapOutlined />
                    SQL Compare
                  </span>
                ),
              },
              {
                key: "score",
                label: (
                  <span>
                    <ExperimentOutlined />
                    SQL Score
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
      </AntApp>
    </ConfigProvider>
  );
}

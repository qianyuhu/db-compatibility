/**
 * WebSocket hook for real-time CFG execution events.
 *
 * Connects to the backend WS endpoint and dispatches
 * node_started / node_finished / node_failed events.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { getWsUrl } from "../api/cfgWorkbench";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WsEvent {
  type: "node_started" | "node_finished" | "node_failed" | "execution_complete";
  node_id: string;
  timestamp: number;
  data?: Record<string, unknown>;
}

export interface UseCfgWebSocketOptions {
  sessionId: string;
  onNodeStarted?: (nodeId: string) => void;
  onNodeFinished?: (nodeId: string, data: Record<string, unknown>) => void;
  onNodeFailed?: (nodeId: string, error: string) => void;
  onExecutionComplete?: () => void;
  onError?: (error: Event) => void;
}

export interface UseCfgWebSocketReturn {
  connected: boolean;
  sendCommand: (command: string, payload?: Record<string, unknown>) => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useCfgWebSocket(
  options: UseCfgWebSocketOptions,
): UseCfgWebSocketReturn {
  const {
    sessionId,
    onNodeStarted,
    onNodeFinished,
    onNodeFailed,
    onExecutionComplete,
    onError,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const url = getWsUrl(sessionId);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WsEvent = JSON.parse(event.data as string);
        switch (msg.type) {
          case "node_started":
            onNodeStarted?.(msg.node_id);
            break;
          case "node_finished":
            onNodeFinished?.(msg.node_id, (msg.data || {}) as Record<string, unknown>);
            break;
          case "node_failed":
            onNodeFailed?.(
              msg.node_id,
              ((msg.data as Record<string, string>)?.error) || "Unknown error",
            );
            break;
          case "execution_complete":
            onExecutionComplete?.();
            break;
        }
      } catch {
        // Ignore parse errors on non-JSON messages
      }
    };

    ws.onerror = (e: Event) => {
      onError?.(e);
    };

    ws.onclose = () => {
      setConnected(false);
      // Reconnect after 3 seconds
      reconnectTimer.current = setTimeout(() => {
        connect();
      }, 3000);
    };
  }, [sessionId, onNodeStarted, onNodeFinished, onNodeFailed, onExecutionComplete, onError]);

  const sendCommand = useCallback(
    (command: string, payload?: Record<string, unknown>) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ command, ...payload }));
      }
    },
    [],
  );

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return {
    connected,
    sendCommand,
  };
}

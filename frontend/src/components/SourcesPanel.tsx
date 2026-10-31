// src/components/SourcesPanel.tsx
/**
 * Data sources panel for the site catalogue (Phase 1, #43).
 * Lists configured industrial sources (OPC UA, CSV, SQL), tests connectivity,
 * displays supported capabilities, and provides an interactive address space browser.
 */

import { useState, useEffect, type ReactElement } from "react";
import type { Translate } from "../findings";
import {
  fetchSources,
  testSource,
  browseSource,
  readSourceLive,
  type SourceInfo,
  type SourceTestResult,
  type AddressSpaceNode,
  type ConnectorLiveValue,
} from "../api";

export interface SourcesPanelProps {
  /** Translation function for localized UI strings. */
  t: Translate;
}

/**
 * Interactive panel displaying data sources configured in `site.json`.
 *
 * In plain words:
 * Connectors are read-only adapters that bridge Crosscut to industrial systems.
 * This panel lets engineers verify that endpoints are reachable, view what operations
 * each driver supports (browse, metadata, history, live read), and explore tags live.
 */
export function SourcesPanel({ t }: SourcesPanelProps): ReactElement {
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [testResults, setTestResults] = useState<Record<string, SourceTestResult | { error: string }>>({});
  const [testingId, setTestingId] = useState<string | null>(null);
  const [activeBrowseId, setActiveBrowseId] = useState<string | null>(null);
  const [browseNodes, setBrowseNodes] = useState<AddressSpaceNode[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [liveValues, setLiveValues] = useState<Record<string, ConnectorLiveValue>>({});

  useEffect(() => {
    let active = true;
    fetchSources()
      .then((res) => {
        if (active) {
          setSources(res.sources || []);
          setLoading(false);
        }
      })
      .catch(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleTest(sourceId: string): Promise<void> {
    setTestingId(sourceId);
    try {
      const res = await testSource(sourceId);
      setTestResults((prev) => ({ ...prev, [sourceId]: res }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestResults((prev) => ({ ...prev, [sourceId]: { error: msg } }));
    } finally {
      setTestingId(null);
    }
  }

  async function handleBrowse(sourceId: string, nodeId?: string): Promise<void> {
    setActiveBrowseId(sourceId);
    setBrowseLoading(true);
    try {
      const res = await browseSource(sourceId, nodeId);
      setBrowseNodes(res.nodes || []);
    } catch {
      setBrowseNodes([]);
    } finally {
      setBrowseLoading(false);
    }
  }

  async function handleReadLive(sourceId: string, nodeId: string): Promise<void> {
    try {
      const res = await readSourceLive(sourceId, [nodeId]);
      if (res.values) {
        setLiveValues((prev) => ({ ...prev, ...res.values }));
      }
    } catch {
      // live read errors stay silent or surfaced in live display
    }
  }

  if (loading) {
    return <div className="sources-loading">{t("configEditor.loading")}</div>;
  }

  return (
    <div className="sources-panel" data-testid="sources-panel">
      <div className="panel-header" style={{ marginBottom: "1rem" }}>
        <h3>{t("catalogue.sources.title")}</h3>
        <p className="description" style={{ color: "var(--muted)", margin: 0 }}>
          {t("catalogue.sources.subtitle")}
        </p>
      </div>

      {sources.length === 0 ? (
        <p className="no-sources">{t("catalogue.sources.none")}</p>
      ) : (
        <div className="source-cards" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {sources.map((src) => {
            const testResult = testResults[src.id];
            const isTesting = testingId === src.id;
            const isBrowsing = activeBrowseId === src.id;

            return (
              <div
                key={src.id}
                className="source-card card"
                data-testid={`source-card-${src.id}`}
                style={{ padding: "1rem", border: "1px solid var(--border)", borderRadius: "6px" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <h4 style={{ margin: "0 0 0.25rem 0" }}>{src.id}</h4>
                    <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                      {t("catalogue.sources.driver")}: <strong>{src.driver}</strong>
                      {src.endpoint ? ` | ${src.endpoint}` : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button
                      type="button"
                      className="button button-secondary"
                      data-testid={`test-source-${src.id}`}
                      disabled={isTesting}
                      onClick={() => void handleTest(src.id)}
                    >
                      {isTesting ? t("catalogue.sources.testing") : t("catalogue.sources.test")}
                    </button>
                    <button
                      type="button"
                      className="button button-outline"
                      data-testid={`browse-source-${src.id}`}
                      onClick={() => void handleBrowse(src.id)}
                    >
                      {t("catalogue.sources.browse")}
                    </button>
                  </div>
                </div>

                {testResult && (
                  <div className="test-outcome" style={{ marginTop: "0.75rem", fontSize: "0.9rem" }}>
                    {"error" in testResult ? (
                      <span style={{ color: "var(--danger)" }}>
                        {t("catalogue.sources.failed")}: {testResult.error}
                      </span>
                    ) : (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <span style={{ color: "var(--success)", fontWeight: 500 }}>
                          ✓ {t("catalogue.sources.connected")}
                        </span>
                        <div style={{ display: "flex", gap: "0.25rem" }}>
                          {testResult.capabilities.map((cap) => (
                            <span
                              key={cap}
                              className="filter-chip filter-chip-active"
                              style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem" }}
                            >
                              {cap}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {isBrowsing && (
                  <div
                    className="browse-results"
                    data-testid="browse-results"
                    style={{
                      marginTop: "1rem",
                      padding: "0.75rem",
                      background: "var(--bg-card)",
                      borderRadius: "4px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                      <strong>{t("catalogue.sources.browse")}: {src.id}</strong>
                      <button
                        type="button"
                        className="button-link"
                        onClick={() => void handleBrowse(src.id)}
                      >
                        {t("catalogue.sources.browseRoot")}
                      </button>
                    </div>

                    {browseLoading ? (
                      <div>{t("catalogue.sources.loading")}</div>
                    ) : (
                      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                        {browseNodes.map((n) => (
                          <li
                            key={n.id}
                            data-testid={`node-${n.id}`}
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              padding: "0.25rem 0",
                              borderBottom: "1px solid var(--border-subtle)",
                            }}
                          >
                            <span>
                              {n.has_children ? "📁 " : "🏷️ "}
                              {n.has_children ? (
                                <button
                                  type="button"
                                  className="button-link"
                                  onClick={() => void handleBrowse(src.id, n.id)}
                                >
                                  {n.name}
                                </button>
                              ) : (
                                <span>{n.name}</span>
                              )}
                              <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: "0.5rem" }}>
                                ({n.node_type})
                              </span>
                            </span>

                            {n.node_type === "variable" && (
                              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                                {liveValues[n.id] && (
                                  <span style={{ fontSize: "0.85rem", fontWeight: "bold" }}>
                                    {liveValues[n.id].value !== null ? liveValues[n.id].value : "N/A"}
                                    <span style={{ fontSize: "0.7rem", color: "var(--muted)", marginLeft: "0.25rem" }}>
                                      (Q:{liveValues[n.id].quality})
                                    </span>
                                  </span>
                                )}
                                <button
                                  type="button"
                                  className="button button-small"
                                  data-testid={`read-live-${n.id}`}
                                  onClick={() => void handleReadLive(src.id, n.id)}
                                >
                                  {t("catalogue.sources.readLive")}
                                </button>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

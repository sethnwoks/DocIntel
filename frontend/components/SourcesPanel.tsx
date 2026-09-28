"use client";

import { useState, useMemo } from "react";
import { DocumentInfo } from "./types";

interface Props {
  documents: DocumentInfo[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onClear: () => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

type StatusFilter = "all" | "completed" | "processing" | "failed" | "pending";

// Colours come from the theme tokens rather than inline hex, so a status badge
// follows the active theme instead of being pinned to one palette.
const statusConfig: Record<string, { label: string; token: string }> = {
  completed: { label: "Completed", token: "ok" },
  processing: { label: "Processing", token: "warn" },
  failed: { label: "Failed", token: "danger" },
  pending: { label: "Pending", token: "idle" },
};

export default function SourcesPanel({
  documents,
  selectedIds,
  onToggle,
  onSelectAll,
  onDeselectAll,
  onClear,
  collapsed = false,
  onToggleCollapse,
}: Props) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const filtered = useMemo(() => {
    let list = documents;
    if (statusFilter !== "all") {
      list = list.filter((d) => d.status === statusFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (d) =>
          d.filename.toLowerCase().includes(q) ||
          d.id.toLowerCase().includes(q)
      );
    }
    return list;
  }, [documents, statusFilter, search]);

  const allSelected =
    documents.length > 0 && documents.every((d) => selectedIds.has(d.id));
  const someSelected =
    documents.some((d) => selectedIds.has(d.id)) && !allSelected;

  const grouped = useMemo(() => {
    const groups: Record<string, DocumentInfo[]> = {};
    filtered.forEach((d) => {
      if (!groups[d.status]) groups[d.status] = [];
      groups[d.status].push(d);
    });
    return groups;
  }, [filtered]);

  const completedCount = documents.filter((d) => d.status === "completed").length;
  const failedCount = documents.filter((d) => d.status === "failed").length;
  const totalChunks = documents.reduce((sum, d) => sum + d.chunk_count, 0);

  return (
    <aside className={`sources-panel${collapsed ? " collapsed" : ""}`}>
      <div className="sources-header">
        <h3 className="sources-title">Sources</h3>
        <div className="sources-actions">
          <span className="sources-count">{documents.length} docs</span>
          {onToggleCollapse && (
            <button className="sources-btn" onClick={onToggleCollapse} aria-label="Collapse sidebar">
              <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="m15 18-6-6 6-6" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="sources-stats">
        <div className="stat">
          <span className="stat-dot completed" />
          <span className="stat-label">{completedCount} ready</span>
          <span className="stat-value">{totalChunks} chunks</span>
        </div>
        {failedCount > 0 && (
          <div className="stat">
            <span className="stat-dot failed" />
            <span className="stat-label">{failedCount} failed</span>
          </div>
        )}
      </div>

      <div className="sources-search">
        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <input
          type="text"
          placeholder="Filter documents…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="search-input"
        />
      </div>

      <div className="sources-filters">
        {(["all", "completed", "processing", "failed", "pending"] as StatusFilter[]).map(
          (filter) => (
            <button
              key={filter}
              className={`filter-btn ${statusFilter === filter ? "active" : ""}`}
              onClick={() => setStatusFilter(filter)}
            >
              {filter === "all" ? "All" : statusConfig[filter]?.label ?? filter}
            </button>
          )
        )}
      </div>

      <div className="sources-actions">
        <button className="sources-btn" onClick={onSelectAll}>
          Select all
        </button>
        <button className="sources-btn" onClick={onDeselectAll}>
          Deselect all
        </button>
        {selectedIds.size > 0 && (
          <button className="sources-btn danger" onClick={onClear}>
            Clear ({selectedIds.size})
          </button>
        )}
      </div>

      {selectedIds.size > 0 && (
        <div className="selected-bar">
          <span>{selectedIds.size} selected</span>
          <button className="selected-clear" onClick={onClear}>
            ✕
          </button>
        </div>
      )}

       <ul className="sources-list">
         {Object.entries(grouped).map(([status, docs]) => (
           <div key={status} className="status-group">
            {status !== "all" && (
              <div className="status-group-label">
                <span
                  className="status-dot"
                  style={{ background: `var(--${statusConfig[status]?.token ?? "idle"})` }}
                />
                <span className="status-group-name">
                  {statusConfig[status]?.label ?? status}
                </span>
                <span className="status-group-count">{docs.length}</span>
              </div>
            )}
            {docs.map((doc) => {
              const isSelected = selectedIds.has(doc.id);
              const cfg = statusConfig[doc.status] || statusConfig.pending;
              return (
                <li
                  key={doc.id}
                  className={`sources-item ${isSelected ? "sources-item-selected" : ""}`}
                  onClick={() => onToggle(doc.id)}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggle(doc.id)}
                    className="sources-checkbox"
                    onClick={(e) => e.stopPropagation()}
                  />
                  <div className="sources-item-content">
                    <span className="sources-filename" title={doc.filename}>
                      {doc.filename}
                    </span>
                    <div className="sources-item-meta">
                      {doc.status === "processing" && (
                        <svg className="progress-ring progress-ring-spin" viewBox="0 0 16 16">
                          <circle cx="8" cy="8" r="5" fill="none" stroke="var(--border)" strokeWidth="2" />
                          <circle
                            cx="8"
                            cy="8"
                            r="5"
                            fill="none"
                            stroke="var(--accent)"
                            strokeWidth="2"
                            strokeDasharray="31.4"
                            strokeDashoffset="10"
                            strokeLinecap="round"
                          />
                        </svg>
                      )}
                      {doc.status === "pending" && (
                        <svg className="progress-ring" viewBox="0 0 16 16">
                          <circle cx="8" cy="8" r="5" fill="none" stroke="var(--border)" strokeWidth="2" />
                        </svg>
                      )}
                      {doc.status === "completed" && (
                        <svg className="progress-ring" viewBox="0 0 16 16">
                          <circle cx="8" cy="8" r="5" fill="var(--accent)" stroke="none" />
                        </svg>
                      )}
                      {doc.status === "failed" && (
                        <svg className="progress-ring" viewBox="0 0 16 16">
                          <circle cx="8" cy="8" r="5" fill="none" stroke="var(--danger)" strokeWidth="2" />
                          <path d="M5 5L11 11M11 5L5 11" stroke="var(--danger)" strokeWidth="1.5" strokeLinecap="round" />
                        </svg>
                      )}
                      <span
                        className="status-badge"
                        style={{
                          color: `var(--${cfg.token})`,
                          background: `var(--${cfg.token}-bg)`,
                        }}
                      >
                        {cfg.label}
                      </span>
                      <span className="sources-chunk-count">
                        {doc.chunk_count} chunks
                      </span>
                    </div>
                  </div>
                </li>
              );
            })}
          </div>
        ))}
        {filtered.length === 0 && (
          <li className="sources-empty">No documents match</li>
        )}
      </ul>
    </aside>
  );
}
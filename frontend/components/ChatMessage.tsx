"use client";

import { useState, useMemo } from "react";
import { Message, Citation } from "./types";

interface Props {
  message: Message;
  onStop?: () => void;
}

// Similarity bands map onto the theme's status tokens so the colour meaning is
// consistent with the document status badges elsewhere in the UI.
function similarityColor(similarity: number) {
  if (similarity >= 0.9) return "var(--ok)";
  if (similarity >= 0.7) return "var(--accent)";
  if (similarity >= 0.5) return "var(--warn)";
  return "var(--danger)";
}

function similarityLabel(similarity: number) {
  if (similarity >= 0.9) return "High";
  if (similarity >= 0.7) return "Med";
  if (similarity >= 0.5) return "Low";
  return "Min";
}

function formatSimilarity(similarity: number) {
  return (similarity * 100).toFixed(1);
}

export default function ChatMessage({ message, onStop }: Props) {
  const [expandedSources, setExpandedSources] = useState<Set<number>>(new Set());
  const [showAllCitations, setShowAllCitations] = useState(false);

  const isUser = message.role === "user";
  const isComparison = message.isComparison === true;
  const displayCitations = showAllCitations
    ? message.citations
    : message.citations?.slice(0, 5);

  const toggleSource = (idx: number) => {
    setExpandedSources((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  if (message.type === "system") {
    return (
      <div className="system-msg">
        <span className="system-line" />
        {message.text}
        <span className="system-line" />
      </div>
    );
  }

  const renderInlineCitations = (text: string, citations: Citation[]) => {
    if (!citations || citations.length === 0) return <>{text}</>;

    const parts: React.ReactNode[] = [];
    let remaining = text;

    citations.forEach((cite, idx) => {
      const marker = `[${idx + 1}]`;
      const pos = remaining.lastIndexOf(marker);
      if (pos === -1) {
        parts.push(remaining);
        return;
      }
      if (pos > 0) {
        parts.push(remaining.slice(0, pos));
      }
      parts.push(
        <span
          key={`cite-${idx}`}
          className="inline-cite"
          onClick={() => toggleSource(idx)}
          title={`${cite.documentId} — ${formatSimilarity(cite.similarity)}% similarity`}
        >
          <sup className="cite-num">{idx + 1}</sup>
        </span>
      );
      remaining = remaining.slice(pos + marker.length);
    });

    if (remaining) {
      parts.push(remaining);
    }

    return parts;
  };

  return (
    <div className={`msg ${message.role}`}>
      <div className={`avatar ${message.role}`}>
        {isUser ? "S" : "AI"}
      </div>
      <div className="bubble">
        {isComparison && message.comparisonEntities && (
          <div className="comparison-badge">
            Comparing:{" "}
            {message.comparisonEntities.map((e, i) => (
              <span key={i} className="compare-entity">
                {e}
              </span>
            ))}
          </div>
        )}

        <div className="bubble-text">
          {message.isStreaming ? (
            <>
              {renderInlineCitations(message.text, message.citations ?? [])}
              <span className="stream-cursor" />
            </>
          ) : (
            renderInlineCitations(message.text, message.citations ?? [])
          )}
        </div>

        {message.citations && message.citations.length > 0 && (
          <div className="cite-block">
            <div className="cite-header">
              <span className="cite-label">
                Sources ({message.citations.length})
              </span>
              {message.citations.length > 5 && (
                <button
                  className="cite-toggle"
                  onClick={() => setShowAllCitations(!showAllCitations)}
                >
                  {showAllCitations ? "Show less" : "Show all"}
                </button>
              )}
            </div>
            {displayCitations?.map((c, i) => (
              <div
                key={i}
                className={`cite-item ${expandedSources.has(i) ? "cite-expanded" : ""}`}
                onClick={() => toggleSource(i)}
              >
                <div className="cite-main">
                  <span className="cite-num">{i + 1}</span>
                  <span className="ci-page">{c.page}</span>
                  {c.bm25 && (
                    <span className="ci-bm25-badge">BM25</span>
                  )}
                  <span
                    className="ci-sim"
                    style={{
                      color: similarityColor(c.similarity),
                      borderColor: similarityColor(c.similarity),
                    }}
                  >
                    {formatSimilarity(c.similarity)}%
                  </span>
                  <span className="ci-sim-label">{similarityLabel(c.similarity)}</span>
                </div>
                <div className="ci-doc">{c.documentId}</div>
                {expandedSources.has(i) && c.excerpt && (
                  <div className="cite-excerpt">{c.excerpt}</div>
                )}
                {!expandedSources.has(i) && c.excerpt && (
                  <div className="cite-excerpt-collapsed">{c.excerpt.slice(0, 80)}…</div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* A "no sources" answer is a retrieval result, not an error. Say what
            was searched so the user can tell the difference between "your
            question isn't in these documents" and "the search didn't run". */}
        {!message.citations?.length && message.role === "bot" && !message.isStreaming && (
          <div className="no-match">
            <span className="no-match-dot" />
            <span>
              {typeof message.searchedDocCount === "number"
                ? message.searchedDocCount === 0
                  ? "No documents were selected, so there was nothing to search."
                  : `Searched ${message.searchedDocCount} document${
                      message.searchedDocCount === 1 ? "" : "s"
                    } — no passage matched closely enough to answer this.`
                : "No passage matched closely enough to answer this."}
            </span>
          </div>
        )}

        {message.isStreaming && (
          <div className="stream-controls">
            <button className="stop-btn" onClick={onStop}>
              <svg width={12} height={12} viewBox="0 0 16 16" fill="currentColor">
                <rect x="2" y="2" width="12" height="12" rx="2" />
              </svg>
              Stop
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
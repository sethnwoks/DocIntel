"use client";

interface Props {
  onChipClick: (text: string) => void;
}

const CHIPS = [
  "Summarize this document",
  "What are the key tables?",
  "Extract all named entities",
  "What are the main findings?",
  "List all dates and deadlines",
];

export default function EmptyState({ onChipClick }: Props) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <svg width={40} height={40} viewBox="0 0 40 40" fill="none">
          <rect x="8" y="4" width="22" height="28" rx="2" stroke="currentColor" strokeWidth={1.6} />
          <path d="M14 12h12M14 18h12M14 24h7" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" />
          <circle cx="30" cy="30" r="7" fill="var(--accent)" />
          <path d="M30 27v6M27 30h6" stroke="var(--accent-text)" strokeWidth={1.8} strokeLinecap="round" />
        </svg>
      </div>
      <p className="empty-title">No document loaded</p>
      <p className="empty-sub">
        Upload a PDF, then ask questions about it
      </p>
      {/* Scope statement. The system only answers from documents the user has
          uploaded - it has no web access and no other tenant's data. Saying so
          up front is the difference between a correct mental model and a user
          expecting general-purpose answers. */}
      <p className="empty-scope">
        Answers come only from your uploaded documents. If the answer is not in
        them, it will say so rather than guess.
      </p>
      <div className="chip-row">
        {CHIPS.map((chip) => (
          <button key={chip} className="chip" onClick={() => onChipClick(chip)}>
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}

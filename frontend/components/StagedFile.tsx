"use client";

import { StagedFileInfo } from "./types";

interface Props {
  file: StagedFileInfo;
  onRemove: () => void;
}

export default function StagedFile({ file, onRemove }: Props) {
  const kb = (file.size / 1024).toFixed(0);

  return (
    <div className="staged-file">
      <svg width={11} height={11} viewBox="0 0 16 16" fill="none">
        <path
          d="M4 2h6l4 4v8a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z"
          stroke="currentColor"
          strokeWidth={1.4}
          strokeLinejoin="round"
        />
        <path d="M10 2v4h4" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" />
      </svg>
      <span className="sf-name">{file.name}</span>
      <span className="sf-size">{kb} KB</span>
      <button className="sf-remove" onClick={onRemove} aria-label="Remove staged file">
        ✕
      </button>
    </div>
  );
}

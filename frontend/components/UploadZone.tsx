"use client";

import { RefObject } from "react";

interface Props {
  fileInputRef: RefObject<HTMLInputElement | null>;
  onFile: (file: File) => void;
  isUploading: boolean;
}

export default function UploadZone({ fileInputRef, onFile, isUploading }: Props) {
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFile(file);
    e.target.value = "";
  };

  return (
    <>
      <label className={`upload-btn ${isUploading ? "uploading" : ""}`} htmlFor="file-input">
        {isUploading ? (
          <>
            <span className="upload-spinner" />
            Uploading…
          </>
        ) : (
          <>
            <svg width={12} height={12} viewBox="0 0 16 16" fill="none">
              <path
                d="M8 2v8M5 5l3-3 3 3M2 11v2a1 1 0 001 1h10a1 1 0 001-1v-2"
                stroke="currentColor"
                strokeWidth={1.4}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Upload document
          </>
        )}
      </label>
      <input
        ref={fileInputRef}
        id="file-input"
        type="file"
        accept=".pdf,.docx,.csv,.txt,.xlsx"
        style={{ display: "none" }}
        onChange={handleChange}
      />
    </>
  );
}

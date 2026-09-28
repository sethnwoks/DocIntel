export interface Citation {
  page: string;
  excerpt: string;
  documentId: string;
  similarity: number;
  bm25?: boolean;
  bbox?: { x: number; y: number; w: number; h: number };
  inlineIndex?: number;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  status: string;
  created_at: string;
  chunk_count: number;
}

export interface Message {
  id: string;
  role: "user" | "bot" | "system";
  text: string;
  type?: "system";
  citations?: Citation[];
  isStreaming?: boolean;
  isComparison?: boolean;
  comparisonEntities?: string[];
  /** How many documents the search actually covered, so a zero-result answer
   *  can say what was searched rather than just "I don't know". */
  searchedDocCount?: number;
}

export interface StagedFileInfo {
  name: string;
  size: number;
  file: File;
}

export interface ComparisonEntity {
  name: string;
  documentId: string;
  chunks: Citation[];
}

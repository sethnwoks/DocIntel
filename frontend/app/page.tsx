"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ChatMessage from "@/components/ChatMessage";
import UploadZone from "@/components/UploadZone";
import ThemeToggle from "@/components/ThemeToggle";
import StagedFile from "@/components/StagedFile";
import EmptyState from "@/components/EmptyState";
import AuthForm from "@/components/AuthForm";
import SourcesPanel from "@/components/SourcesPanel";
import { Message, StagedFileInfo, DocumentInfo } from "@/components/types";

type AuthState = "checking" | "authenticated" | "unauthenticated";

export default function Home() {
  const [authState, setAuthState] = useState<AuthState>("checking");

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [stagedFile, setStagedFile] = useState<StagedFileInfo | null>(null);
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set());
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const chatBodyRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const pollingRef = useRef<number | null>(null);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await fetch("http://localhost:8000/api/documents/", {
        credentials: "include",
      });
      if (res.ok) {
        const data: DocumentInfo[] = await res.json();
        setDocuments(data);
      }
    } catch {
      // silently fail — panel will just be empty
    }
  }, []);

  useEffect(() => {
    const hasInFlight = documents.some(
      (d) => d.status === "pending" || d.status === "processing"
    );
    if (hasInFlight && !pollingRef.current) {
      pollingRef.current = window.setInterval(() => {
        fetchDocuments();
      }, 2000);
    } else if (!hasInFlight && pollingRef.current) {
      window.clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [documents, fetchDocuments]);

  useEffect(() => {
    fetch("http://localhost:8000/api/auth/me", {
      credentials: "include",
    })
      .then((res) => {
        if (res.ok) {
          setAuthState("authenticated");
          fetchDocuments();
        } else {
          setAuthState("unauthenticated");
        }
      })
      .catch(() => {
        setAuthState("unauthenticated");
      });
  }, [fetchDocuments]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Only follow the conversation if the user is already at the bottom. Yanking
  // someone to the end of a long answer they have started reading loses their
  // place; it is disorienting rather than helpful.
  const stickToBottomRef = useRef(true);

  useEffect(() => {
    const el = chatBodyRef.current;
    if (!el) return;
    const onScroll = () => {
      stickToBottomRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const el = chatBodyRef.current;
    if (el && stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, isTyping]);

  const autoResize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  };

  const handleFileStage = (file: File) => {
    const allowedTypes = [
      "application/pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "text/csv",
      "text/plain",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ];
    if (!allowedTypes.includes(file.type) && !file.name.match(/\.(pdf|docx|csv|txt|xlsx)$/i)) {
      alert("Unsupported file type. Please upload a PDF, DOCX, CSV, TXT, or XLSX.");
      return;
    }
    setStagedFile({ name: file.name, size: file.size, file });
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileStage(file);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleLogout = async () => {
    await fetch("http://localhost:8000/api/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    setAuthState("unauthenticated");
    setMessages([]);
    setSelectedDocIds(new Set());
  };

  const toggleDoc = (docId: string) => {
    setSelectedDocIds((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) {
        next.delete(docId);
      } else {
        next.add(docId);
      }
      return next;
    });
  };

  const selectAllDocs = () => {
    setSelectedDocIds(new Set(documents.map((d) => d.id)));
  };

  const deselectAllDocs = () => {
    setSelectedDocIds(new Set());
  };

  const clearDocSelection = () => {
    setSelectedDocIds(new Set());
    setMessages([]);
  };

  const stopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    setIsTyping(false);
  };

  const sendMessage = async () => {
    if ((!input.trim() && !stagedFile) || isStreaming) return;

    const newMessages: Message[] = [...messages];

    if (stagedFile) {
      setIsUploading(true);
      try {
        const formData = new FormData();
        formData.append("file", stagedFile.file);

        const res = await fetch("http://localhost:8000/api/upload/", {
          method: "POST",
          credentials: "include",
          body: formData,
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        newMessages.push({
          id: Date.now().toString(),
          role: "system",
          text: `Document uploaded: ${stagedFile.name} · ID: ${data.document_id} · Status: ${data.status}`,
          type: "system",
        });
        await fetchDocuments();
      } catch (err: any) {
        newMessages.push({
          id: Date.now().toString(),
          role: "system",
          text: `Upload failed: ${err.message}`,
          type: "system",
        });
      } finally {
        setIsUploading(false);
        setStagedFile(null);
      }
    }

    const userQuestion = input.trim();
    if (userQuestion) {
      const userMsg: Message = {
        id: Date.now().toString() + "-u",
        role: "user",
        text: userQuestion,
      };
      newMessages.push(userMsg);
    }

    setMessages(newMessages);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "";

    if (userQuestion) {
      setIsTyping(true);
      setIsStreaming(true);

      const botMsgId = Date.now().toString() + "-b";
      const abortCtrl = new AbortController();
      abortControllerRef.current = abortCtrl;

      try {
        const body: Record<string, unknown> = { question: userQuestion };
        if (selectedDocIds.size > 0) {
          body.document_ids = Array.from(selectedDocIds);
        }

        const res = await fetch("http://localhost:8000/api/query/", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: abortCtrl.signal,
        });

        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        const isComparison =
          userQuestion.toLowerCase().includes("compare") ||
          userQuestion.toLowerCase().includes("versus") ||
          userQuestion.toLowerCase().includes("vs ");

        const comparisonEntities = isComparison
          ? userQuestion
              .replace(/compare|versus|vs/gi, "")
              .split(/and|&/)
              .map((s: string) => s.trim())
              .filter(Boolean)
          : undefined;

        setMessages((prev) => [
          ...prev,
          {
            id: botMsgId,
            role: "bot",
            text: data.answer,
            citations: (data.sources ?? []).map((src: any) => ({
              page: `${src?.filename || 'unknown'} (chunk ${src?.chunk_index ?? 0})`,
              excerpt: "",
              documentId: src?.document_id || "unknown",
              similarity: src?.similarity ?? 1.0,
              bm25: src?.bm25 ?? false,
              inlineIndex: 0,
            })),
            isComparison: isComparison,
            comparisonEntities: comparisonEntities,
            searchedDocCount:
              selectedDocIds.size > 0 ? selectedDocIds.size : documents.length,
          },
        ]);
      } catch (err: any) {
        if (err.name === "AbortError") {
          setMessages((prev) => [
            ...prev,
            {
              id: botMsgId,
              role: "bot",
              text: "Response stopped by user.",
              type: "system",
            },
          ]);
        } else {
          setMessages((prev) => [
            ...prev,
            {
              id: botMsgId,
              role: "system",
              text: `Query failed: ${err.message}`,
              type: "system",
            },
          ]);
        }
      } finally {
        setIsTyping(false);
        setIsStreaming(false);
        abortControllerRef.current = null;
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const fillPrompt = (text: string) => {
    setInput(text);
    textareaRef.current?.focus();
  };

  const selectedDocNames = documents
    .filter((d) => selectedDocIds.has(d.id))
    .map((d) => d.filename);

  if (authState === "checking") {
    return (
      <div className="auth-shell">
        <div className="upload-spinner" style={{ width: 20, height: 20, borderWidth: 2 }} />
      </div>
    );
  }

  if (authState === "unauthenticated") {
    return (
      <AuthForm
        onAuthSuccess={() => setAuthState("authenticated")}
      />
    );
  }

  return (
    <div
      className="shell"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      {isDragging && <div className="drag-overlay">Drop your document here</div>}

      <header className="topbar">
        <div className="topbar-left">
          <div className="logo-mark">
            <svg viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" width={14} height={14}>
              <path d="M3 7h8M7 3v8" stroke="currentColor" strokeWidth={2} strokeLinecap="round" />
            </svg>
          </div>
          <div className="title-block">
            <span className="app-name">DocIntel</span>
            <span className="app-sub">multitenant · hybrid RAG</span>
          </div>
        </div>

        <div className="topbar-right">
          {selectedDocNames.length > 0 && (
            <div className="doc-pill">
              <svg width={12} height={12} viewBox="0 0 16 16" fill="none">
                <path d="M4 2h6l4 4v8a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="currentColor" strokeWidth={1.4} strokeLinejoin="round" />
                <path d="M10 2v4h4" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" />
              </svg>
              <span className="doc-name">{selectedDocNames.length} doc{selectedDocNames.length > 1 ? "s" : ""}</span>
              <button className="doc-remove" onClick={clearDocSelection} aria-label="Clear document selection">✕</button>
            </div>
          )}
          <ThemeToggle theme={theme} onToggle={() => setTheme((t) => (t === "dark" ? "light" : "dark"))} />
          <button
            className="upload-btn"
            onClick={handleLogout}
            title="Logout"
            id="logout-btn"
          >
            Logout
          </button>
        </div>
      </header>

      <div className="main-layout">
        <SourcesPanel
          documents={documents}
          selectedIds={selectedDocIds}
          onToggle={toggleDoc}
          onSelectAll={selectAllDocs}
          onDeselectAll={deselectAllDocs}
          onClear={clearDocSelection}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
        />

        <main className="chat-body" ref={chatBodyRef}>
          <button
            className="sources-toggle"
            onClick={() => setSidebarCollapsed((c) => !c)}
            aria-label={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
            title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
          >
            <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>
          {messages.length === 0 && !isTyping ? (
            <EmptyState onChipClick={fillPrompt} />
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  onStop={stopStreaming}
                />
              ))}
              {isTyping && !isStreaming && (
                <div className="msg bot">
                  <div className="avatar bot">AI</div>
                  <div className="typing-bubble">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      <footer className="input-zone">
        <div className="upload-strip">
          <UploadZone
            fileInputRef={fileInputRef}
            onFile={handleFileStage}
            isUploading={isUploading}
          />
          {stagedFile && (
            <StagedFile file={stagedFile} onRemove={() => setStagedFile(null)} />
          )}
        </div>

        <div className="compose">
          <textarea
            ref={textareaRef}
            className="prompt-input"
            placeholder={
              isStreaming
                ? "Generating…"
                : selectedDocNames.length > 0
                ? `Ask about ${selectedDocNames[0]}…`
                : "Upload a document, then ask anything…"
            }
            value={input}
            onChange={(e) => { setInput(e.target.value); autoResize(); }}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={isStreaming}
          />
          <button
            className="send-btn"
            onClick={sendMessage}
            disabled={(!input.trim() && !stagedFile) || isStreaming}
            aria-label="Send message"
          >
            {isStreaming ? (
              <svg viewBox="0 0 16 16" fill="none" width={15} height={15}>
                <rect x="2" y="2" width="12" height="12" rx="2" stroke="currentColor" strokeWidth={1.5} />
              </svg>
            ) : (
              <svg viewBox="0 0 16 16" fill="none" width={15} height={15}>
                <path d="M2 14L14 8 2 2v5l8 1-8 1v5z" fill="currentColor" />
              </svg>
            )}
          </button>
        </div>

        <div className="status-bar">
          <span className="hint">Shift+Enter for new line · drag &amp; drop supported</span>
          <span className="model-tag">
            <span className="status-dot" />
            pgvector · OpenAI
          </span>
        </div>
      </footer>
    </div>
  );
}
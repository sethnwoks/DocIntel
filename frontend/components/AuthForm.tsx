"use client";

import { useState } from "react";

interface AuthFormProps {
  onAuthSuccess: (userId: string, tenantId: string) => void;
}

type Mode = "login" | "signup";

export default function AuthForm({ onAuthSuccess }: AuthFormProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    const endpoint =
      mode === "login"
        ? "http://localhost:8000/api/auth/login"
        : "http://localhost:8000/api/auth/signup";

    const body =
      mode === "login"
        ? { email, password }
        : { email, password, organization_name: orgName };

    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // credentials: "include" tells the browser to accept and store
        // the HttpOnly cookie that FastAPI sets in the response
        credentials: "include",
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data.detail ?? "Something went wrong.");
        return;
      }

      const data = await res.json();
      // The cookie is now silently stored in the browser.
      // We just surface the user/tenant IDs to the parent so it can
      // update its auth state and show the main chat UI.
      onAuthSuccess(data.user_id, data.tenant_id);
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="auth-card">
        {/* Logo */}
        <div className="auth-logo">
          <div className="logo-mark">
            <svg viewBox="0 0 14 14" fill="none" width={14} height={14}>
              <path
                d="M3 7h8M7 3v8"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
              />
            </svg>
          </div>
          <div className="title-block">
            <span className="app-name">DocIntel</span>
            <span className="app-sub">multitenant · hybrid RAG</span>
          </div>
        </div>

        {/* Mode tabs */}
        <div className="auth-tabs">
          <button
            className={`auth-tab ${mode === "login" ? "active" : ""}`}
            onClick={() => { setMode("login"); setError(null); }}
            type="button"
          >
            Login
          </button>
          <button
            className={`auth-tab ${mode === "signup" ? "active" : ""}`}
            onClick={() => { setMode("signup"); setError(null); }}
            type="button"
          >
            Sign up
          </button>
        </div>

        {/* Form */}
        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === "signup" && (
            <div className="auth-field">
              <label className="auth-label" htmlFor="org-name">
                Organisation name
              </label>
              <input
                id="org-name"
                className="auth-input"
                type="text"
                placeholder="Acme Corp"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                required
                autoComplete="organization"
              />
            </div>
          )}

          <div className="auth-field">
            <label className="auth-label" htmlFor="auth-email">
              Email
            </label>
            <input
              id="auth-email"
              className="auth-input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div className="auth-field">
            <label className="auth-label" htmlFor="auth-password">
              Password
            </label>
            <input
              id="auth-password"
              className="auth-input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </div>

          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}

          <button
            className="auth-submit"
            type="submit"
            disabled={isLoading}
            id="auth-submit-btn"
          >
            {isLoading ? (
              <span className="upload-spinner" />
            ) : mode === "login" ? (
              "Login"
            ) : (
              "Create account"
            )}
          </button>
        </form>

        <p className="auth-footer">
          {mode === "login" ? "No account? " : "Already have one? "}
          <button
            className="auth-switch"
            type="button"
            onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}
          >
            {mode === "login" ? "Sign up" : "Login"}
          </button>
        </p>
      </div>
    </div>
  );
}

# DocIntel — Frontend

Multitenant hybrid RAG chatbot UI. Built with Next.js 15, TypeScript, and IBM Plex Mono + Syne.

---

## Setup

```bash
npm install
npm run dev
```

Opens at `http://localhost:3000`.

---

## Project structure

```
docintel/
├── app/
│   ├── layout.tsx        # Root layout, font imports, theme attribute
│   ├── page.tsx          # Main page — all state lives here
│   └── globals.css       # All styles + light/dark CSS variables
├── components/
│   ├── types.ts          # Message, StagedFileInfo, Citation interfaces
│   ├── ChatMessage.tsx   # Renders user/bot/system messages + citations
│   ├── UploadZone.tsx    # Upload button + file input
│   ├── StagedFile.tsx    # Staged file pill before send
│   ├── ThemeToggle.tsx   # Sun/moon toggle button
│   └── EmptyState.tsx    # Empty chat with prompt chips
├── next.config.ts        # Rewrites /api/v1/* → FastAPI at :8000
├── package.json
├── tailwind.config.ts
└── tsconfig.json
```

---

## Wiring to FastAPI

All TODO blocks are in `app/page.tsx`. Two calls to wire:

### 1. Document upload

Find the comment `// TODO: Replace with your FastAPI upload call` and replace:

```ts
const formData = new FormData();
formData.append("file", stagedFile.file);

const res = await fetch("/api/v1/documents/upload", {
  method: "POST",
  body: formData,
});

const data = await res.json();
const fileId = data.file_id; // store this in state
```

### 2. Chat query

Find the comment `// TODO: Replace with your FastAPI chat call` and replace:

```ts
const res = await fetch("/api/v1/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    query: input.trim(),
    file_id: currentFileId,     // the ID from the upload response
    tenant_id: "default",       // wire to your multitenant logic
  }),
});

const data = await res.json();

const botMsg: Message = {
  id: Date.now().toString() + "-b",
  role: "bot",
  text: data.answer,
  citations: data.citations,    // [{ page, excerpt, bbox }]
};
```

The `next.config.ts` already rewrites `/api/v1/*` to `http://localhost:8000/api/v1/*` so no CORS issues in dev.

---

## Theme

Toggle is top-right. Dark by default. Controlled via `data-theme` on `<html>`.

All color tokens are CSS variables in `globals.css` under `:root` (dark) and `[data-theme="light"]`.

To persist theme preference across reloads, add `localStorage` in `app/page.tsx`:

```ts
const [theme, setTheme] = useState<"light" | "dark">(() => {
  if (typeof window !== "undefined") {
    return (localStorage.getItem("theme") as "light" | "dark") ?? "dark";
  }
  return "dark";
});

useEffect(() => {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
}, [theme]);
```

---

## Features

- Light/dark toggle with full CSS variable theming
- Drag and drop file upload (PDF, DOCX, CSV, TXT, XLSX)
- Staged file preview before send
- Active document pill in topbar with dismiss
- Message animations (fade up)
- Typing indicator (three-dot bounce)
- Citation blocks on bot messages with page + excerpt
- System messages for document load events
- Auto-resizing textarea (Shift+Enter for newline)
- Prompt chips on empty state
- Responsive (mobile-first breakpoints in globals.css)
- Scrollable chat body with thin scrollbar
- Send button disabled when input is empty

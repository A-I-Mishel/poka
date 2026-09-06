import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, ChatMessage } from "./api";
import "./theme.css";

/* ---------------- icons (from approved design) ---------------- */
const I = {
  search: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
  ),
  memory: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M15 2v2" /><path d="M15 20v2" /><path d="M2 15h2" /><path d="M2 9h2" /><path d="M20 15h2" /><path d="M20 9h2" /><path d="M9 2v2" /><path d="M9 20v2" /></svg>
  ),
  folder: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /></svg>
  ),
  box: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></svg>
  ),
  link: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" /></svg>
  ),
  bars: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" x2="12" y1="20" y2="10" /><line x1="18" x2="18" y1="20" y2="4" /><line x1="6" x2="6" y1="20" y2="16" /></svg>
  ),
  chev: (
    <svg className="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
  ),
  back: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m12 19-7-7 7-7" /><path d="M19 12H5" /></svg>
  ),
  clip: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>
  ),
  camera: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" /><circle cx="12" cy="13" r="3" /></svg>
  ),
  photo: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /></svg>
  ),
  doc: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /></svg>
  ),
  send: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>
  ),
  down: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></svg>
  ),
  open: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
  ),
  flask: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2v7.31" /><path d="M14 9.3V1.99" /><path d="M8.5 2h7" /><path d="M14 9.3a6.5 6.5 0 1 1-4 0" /><path d="M5.52 16h12.96" /></svg>
  ),
  bolt: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
  ),
  brain: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" /><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" /><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" /></svg>
  ),
  globe: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" /><path d="M2 12h20" /></svg>
  ),
  check: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>
  ),
};

function BugIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="#2d2350"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m8 2 1.88 1.88" />
      <path d="M14.12 3.88 16 2" />
      <path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1" />
      <path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6" />
      <path d="M12 20v-9" />
      <path d="M6.53 9C4.6 8.8 3 7.1 3 5" />
      <path d="M6 13H2" />
      <path d="M3 21c0-2.1 1.7-3.9 3.8-4" />
      <path d="M20.97 5c0 2.1-1.6 3.8-3.5 4" />
      <path d="M22 13h-4" />
      <path d="M17.2 17c2.1.1 3.8 1.9 3.8 4" />
    </svg>
  );
}

/* ---------------- small helpers (no hardcoded content) ---------------- */
function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, "0");
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${String(h).padStart(2, "0")}:${m} ${ap}`;
}

function dayLabel(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const now = new Date();
  const day = (x: Date) => x.getFullYear() * 1000 + x.getMonth() * 40 + x.getDate();
  const diff = day(now) - day(d);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function fmtSize(b?: number): string {
  if (b === undefined || b === null) return "";
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(1)} MB`;
}

const EXT_COLORS: Record<string, { label: string; color: string }> = {
  pdf: { label: "PDF", color: "#f87171" },
  doc: { label: "DOC", color: "#60a5fa" },
  docx: { label: "DOC", color: "#60a5fa" },
  ppt: { label: "PPT", color: "#fbbf24" },
  pptx: { label: "PPT", color: "#fbbf24" },
  xls: { label: "XLS", color: "#34d399" },
  xlsx: { label: "XLS", color: "#34d399" },
  csv: { label: "CSV", color: "#34d399" },
  txt: { label: "TXT", color: "#9b9baa" },
  md: { label: "MD", color: "#c9b8fd" },
  png: { label: "IMG", color: "#22d3ee" },
  jpg: { label: "IMG", color: "#22d3ee" },
  jpeg: { label: "IMG", color: "#22d3ee" },
};
function extMeta(name: string) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  return (
    EXT_COLORS[ext] || {
      label: (ext || "file").slice(0, 4).toUpperCase(),
      color: "#9b9baa",
    }
  );
}

async function copyText(text: string, done: () => void) {
  try {
    await navigator.clipboard.writeText(text);
    done();
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      done();
    } catch {
      /* ignore */
    }
    document.body.removeChild(ta);
  }
}

function downloadBlob(name: string, text: string, type = "text/markdown") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

interface PendingFile {
  id: string;
  kind: string;
  name: string;
  size?: number;
  preview?: string;
}

type Section = "research" | "memory" | "files" | "artifacts" | "sources" | "stats";

const SECTION_TITLES: Record<Section, { title: string; sub: string }> = {
  research: { title: "Research", sub: "Saved research reports from search-backed answers." },
  memory: { title: "Memory", sub: "Things Poka remembers across conversations. Hover a card to forget it." },
  files: { title: "Files", sub: "Documents shared in this workspace." },
  artifacts: { title: "Artifacts", sub: "Generated documents, code, and visuals." },
  sources: { title: "Sources", sub: "Cited sources from briefs and the open conversation." },
  stats: { title: "Stats", sub: "Your usage over the last 7 days." },
};

const ART_STYLE: Record<string, { g: string; e: string }> = {
  pptx: { g: "linear-gradient(135deg,#8b5cf6,#6d28d9)", e: "📊" },
  docx: { g: "linear-gradient(135deg,#38bdf8,#1d4ed8)", e: "📄" },
  doc: { g: "linear-gradient(135deg,#38bdf8,#1d4ed8)", e: "📄" },
  file: { g: "linear-gradient(135deg,#64748b,#334155)", e: "📁" },
};
function artStyle(kind: string) {
  return ART_STYLE[kind] || ART_STYLE.file;
}

/* ================= App ================= */
export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chats, setChats] = useState<any[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [chatFilter, setChatFilter] = useState("");
  const [projects, setProjects] = useState<any[]>([]);
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [addingProject, setAddingProject] = useState(false);
  const [tiers, setTiers] = useState<string[]>([]);
  const [allTiers, setAllTiers] = useState<string[]>([]);
  const [activeTier, setActiveTier] = useState<string | null>(null);
  const [tierMenu, setTierMenu] = useState(false);
  const [deepMode, setDeepMode] = useState(false);
  const [forceSearch, setForceSearch] = useState(false);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [sending, setSending] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState("");
  const [section, setSection] = useState<Section | null>(null);
  const [moreOpen, setMoreOpen] = useState(true);
  const [artifacts, setArtifacts] = useState<{ id: string; kind: string; name: string }[]>([]);
  const [uploads, setUploads] = useState<{ id: string; kind: string; name: string }[]>([]);
  const [briefs, setBriefs] = useState<any[]>([]);
  const [facts, setFacts] = useState<any[]>([]);
  const [researchFilter, setResearchFilter] = useState("");
  const [token, setToken] = useState(() => localStorage.getItem("poka_token") || "");
  const [showToken, setShowToken] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [kebabId, setKebabId] = useState<string | null>(null);
  const [camOpen, setCamOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const toggleRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);
  const photoRef = useRef<HTMLInputElement>(null);
  const docRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const camStreamRef = useRef<MediaStream | null>(null);
  const [camError, setCamError] = useState("");
  const [shotTaken, setShotTaken] = useState(false);

  /* ----- initial load ----- */
  useEffect(() => {
    (async () => {
      try {
        const [h, t, c, p, a, b, u, f] = await Promise.all([
          api.health(),
          api.tiers(),
          api.getChats(),
          api.projects(),
          api.artifacts(),
          api.briefs(),
          api.uploads(),
          api.facts(),
        ]);
        setTiers(h.tiers);
        setAllTiers(t.tiers);
        if (h.tiers.length) setActiveTier(h.tiers[0]);
        setChats(c.chats);
        setMessages(c.current);
        setProjects(p);
        setArtifacts(a);
        setBriefs(b);
        setUploads(u);
        setFacts(f);
      } catch (e: any) {
        setError(e.message || "Backend unreachable. Is the server running?");
      }
    })();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking, section]);

  /* ----- mode-thumb measurement (from design) ----- */
  const placeThumb = React.useCallback(() => {
    const toggle = toggleRef.current;
    const thumb = thumbRef.current;
    if (!toggle || !thumb) return;
    const btn = toggle.querySelector(".mode-btn.active") as HTMLElement | null;
    if (!btn) return;
    const tr = toggle.getBoundingClientRect();
    const br = btn.getBoundingClientRect();
    thumb.style.width = `${br.width}px`;
    thumb.style.transform = `translateX(${br.left - tr.left - toggle.clientLeft}px)`;
  }, []);

  useLayoutEffect(() => {
    placeThumb();
  }, [deepMode, placeThumb]);

  useEffect(() => {
    window.addEventListener("resize", placeThumb);
    if (document.fonts?.ready) document.fonts.ready.then(placeThumb).catch(() => {});
    const t = setTimeout(placeThumb, 300);
    return () => {
      window.removeEventListener("resize", placeThumb);
      clearTimeout(t);
    };
  }, [placeThumb]);

  /* ----- global keys: Alt+M / Alt+S / Esc ----- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.code === "KeyM") {
        e.preventDefault();
        setDeepMode((v) => !v);
      }
      if (e.altKey && e.code === "KeyS") {
        e.preventDefault();
        setForceSearch((v) => !v);
      }
      if (e.key === "Escape") {
        setAttachOpen(false);
        setCamOpen(false);
        setTierMenu(false);
        setKebabId(null);
        setSidebarOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function autosize() {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }

  const chatTitle = (() => {
    const first = messages.find((m) => m.role === "user");
    const text = first ? first.content.trim().slice(0, 34) : "";
    return text || "New chat";
  })();

  async function refreshLists() {
    try {
      const [c, a, b, u] = await Promise.all([
        api.getChats(),
        api.artifacts(),
        api.briefs(),
        api.uploads(),
      ]);
      setChats(c.chats);
      setArtifacts(a);
      setBriefs(b);
      setUploads(u);
      return c;
    } catch {
      return null;
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setError("");
    setSending(true);
    setThinking(true);
    setSection(null);
    const userMsg: ChatMessage = {
      role: "user",
      content: text,
      attachments: pending.map((p) => ({ id: p.id, kind: p.kind, name: p.name })),
    };
    pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview));
    setMessages((m) => [...m, userMsg, { role: "assistant", content: "" }]);
    setInput("");
    setPending([]);
    requestAnimationFrame(autosize);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const result = await api.stream(
        {
          content: text,
          upload_ids: (userMsg.attachments || []).map((a) => a.id),
          project_id: activeProject,
          deep_mode: deepMode,
          force_search: forceSearch,
          active_tier: activeTier,
        },
        (cumulative) =>
          setMessages((m) => {
            const next = [...m];
            next[next.length - 1] = { ...next[next.length - 1], content: cumulative };
            return next;
          }),
        ctrl.signal,
      );
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = result.message;
        return next;
      });
      if (result.active_tier) setActiveTier(result.active_tier);
      await refreshLists();
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setError(e.message || "Request failed.");
        setMessages((m) => m.slice(0, -1));
      }
    } finally {
      setSending(false);
      setThinking(false);
      abortRef.current = null;
    }
  }

  async function regenerate(index: number) {
    if (sending) return;
    setError("");
    setSending(true);
    setThinking(true);
    try {
      const result = await api.regenerate({
        index,
        project_id: activeProject,
        deep_mode: deepMode,
        force_search: forceSearch,
        active_tier: activeTier,
      });
      setMessages((m) => [...m, result.message]);
      if (result.active_tier) setActiveTier(result.active_tier);
      await refreshLists();
    } catch (e: any) {
      setError(e.message || "Regenerate failed.");
    } finally {
      setSending(false);
      setThinking(false);
    }
  }

  async function truncateAndEdit(index: number, text: string) {
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const stored = localStorage.getItem("poka_token") || "";
      if (stored) headers.Authorization = `Bearer ${stored}`;
      const res = await fetch("/api/chats/truncate", {
        method: "POST",
        headers,
        body: JSON.stringify({ index }),
      });
      if (!res.ok) throw new Error("Could not edit that message.");
      const body = await res.json();
      setMessages(body.current);
      setInput(text);
      requestAnimationFrame(() => {
        autosize();
        textareaRef.current?.focus();
      });
    } catch (e: any) {
      setError(e.message || "Could not edit that message.");
    }
  }

  async function uploadFiles(files: FileList | File[]) {
    for (const file of Array.from(files).slice(0, 5 - pending.length)) {
      try {
        const meta = await api.upload(file);
        const preview =
          file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
        setPending((p) => [...p, { ...meta, size: file.size, preview }].slice(0, 5));
      } catch (e: any) {
        setError(e.message || "Upload rejected.");
      }
    }
  }

  /* ----- camera ----- */
  async function openCamera() {
    setCamOpen(true);
    setCamError("");
    setShotTaken(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 960 } },
        audio: false,
      });
      camStreamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
    } catch {
      camStreamRef.current = null;
      setCamError(
        "Camera unavailable — permission denied or no device found. Allow camera access and try again.",
      );
    }
  }
  /* Re-attach the live stream whenever the <video> element (re)mounts. */
  useEffect(() => {
    if (camOpen && !shotTaken && !camError && camStreamRef.current && videoRef.current) {
      videoRef.current.srcObject = camStreamRef.current;
    }
  }, [camOpen, shotTaken, camError]);
  function stopCamera() {
    camStreamRef.current?.getTracks().forEach((t) => t.stop());
    camStreamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }
  function closeCamera() {
    stopCamera();
    setCamOpen(false);
    setShotTaken(false);
    setCamError("");
  }
  function captureShot() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !video.videoWidth) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    setShotTaken(true);
  }
  function useShot() {
    canvasRef.current?.toBlob((blob) => {
      if (blob) {
        uploadFiles([new File([blob], `photo-${Date.now()}.png`, { type: "image/png" })]);
      }
      closeCamera();
    }, "image/png");
  }

  function exportChat() {
    const lines = [`# Poka Chat Export\n`, `Exported: ${new Date().toLocaleString()}\n\n`];
    for (const m of messages) {
      lines.push(`## ${m.role === "user" ? "You" : "Poka"}\n\n${m.content}\n\n---\n\n`);
    }
    downloadBlob("poka-chat.md", lines.join(""));
  }

  const filteredChats = chats.filter((c) =>
    String(c.title || "Untitled").toLowerCase().includes(chatFilter.toLowerCase()),
  );

  const placeholder = deepMode
    ? "Ask something complex — take your time…"
    : forceSearch
      ? "Search the web or ask anything…"
      : "Message Poka…";

  return (
    <div className="app">
      <aside className={`sidebar${sidebarOpen ? " drawer-open" : ""}`}>
        <div className="logo">
          <div className="logo-icon">
            <BugIcon size={16} />
          </div>
          <div>
            <div className="logo-name">Poka</div>
            <div className="logo-sub">AI assistant</div>
          </div>
        </div>

        <button
          className="btn-new"
          onClick={async () => {
            const s = await api.newChat(activeProject, openId);
            setChats(s.chats);
            setMessages(s.current);
            setOpenId(null);
            setSection(null);
            setSidebarOpen(false);
          }}
        >
          + New chat
        </button>
        <input
          className="search"
          type="text"
          placeholder="Search…"
          value={chatFilter}
          onChange={(e) => setChatFilter(e.target.value)}
        />

        <div className="section-label">Projects</div>
        <div className="proj-row">
          <button
            className={`nav-item${activeProject === null ? " active" : ""}`}
            onClick={() => setActiveProject(null)}
          >
            Personal
          </button>
          <button className="add-btn" title="New project" onClick={() => setAddingProject((v) => !v)}>
            +
          </button>
        </div>
        {addingProject && (
          <form
            className="inline-form"
            onSubmit={async (e) => {
              e.preventDefault();
              const name = (new FormData(e.currentTarget).get("name") as string)?.trim();
              if (!name) return;
              try {
                const p = await api.createProject(name);
                setProjects(await api.projects());
                setActiveProject(p.id);
              } catch (err: any) {
                setError(err.message || "Could not create project.");
              }
              setAddingProject(false);
            }}
          >
            <input name="name" placeholder="Project name" maxLength={60} autoFocus />
            <button type="submit">Add</button>
          </form>
        )}
        <div className="stack">
          {projects.map((p) => (
            <div className="recent" key={p.id}>
              <span
                onClick={() => setActiveProject(p.id)}
                style={activeProject === p.id ? { fontWeight: 500 } : undefined}
                className={activeProject === p.id ? "active" : ""}
              >
                {p.name}
              </span>
            </div>
          ))}
        </div>

        <div className="section-label">Recents</div>
        <div className="stack">
          {filteredChats.slice(0, 20).map((c) => (
            <div className={`recent${openId === c.id ? " active" : ""}`} key={c.id}>
              {renamingId === c.id ? (
                <form
                  className="inline-form"
                  style={{ flex: 1 }}
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const title = (new FormData(e.currentTarget).get("title") as string)?.trim();
                    if (title) {
                      const s = await api.renameChat(c.id, title);
                      setChats(s.chats);
                    }
                    setRenamingId(null);
                  }}
                >
                  <input name="title" defaultValue={c.title} maxLength={120} autoFocus />
                </form>
              ) : (
                <span
                  onClick={async () => {
                    const s = await api.openChat(c.id);
                    setChats(s.chats);
                    setMessages(s.current);
                    setOpenId(c.id);
                    setActiveProject(c.project_id || null);
                    setSection(null);
                    setSidebarOpen(false);
                  }}
                >
                  {c.title || "Untitled"}
                </span>
              )}
              <button
                className="kebab"
                onClick={() => setKebabId(kebabId === c.id ? null : c.id)}
              >
                ⋯
              </button>
              {kebabId === c.id && (
                <div className="pop-menu" style={{ position: "absolute" }}>
                  <button
                    onClick={() => {
                      setRenamingId(c.id);
                      setKebabId(null);
                    }}
                  >
                    Rename
                  </button>
                  <button
                    onClick={async () => {
                      const s = await api.deleteChat(c.id);
                      setChats(s.chats);
                      if (openId === c.id) {
                        setOpenId(null);
                        setMessages([]);
                      }
                      setKebabId(null);
                    }}
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        <hr className="rule" />

        <div className="section-label">Workspace</div>
        <div className="stack">
          <button
            className={`nav-item${section === "research" ? " active" : ""}`}
            onClick={() => {
              setSection("research");
              setSidebarOpen(false);
            }}
          >
            {I.search} Research
          </button>
        </div>

        <div className="section-label">More</div>
        <button
          className={`nav-item more-toggle${moreOpen ? "" : " collapsed"}`}
          onClick={() => setMoreOpen((v) => !v)}
        >
          More {I.chev}
        </button>
        <div className={`stack more-items${moreOpen ? "" : " collapsed"}`}>
          {(
            [
              ["memory", I.memory, "Memory"],
              ["files", I.folder, "Files"],
              ["artifacts", I.box, "Artifacts"],
              ["sources", I.link, "Sources"],
              ["stats", I.bars, "Stats"],
            ] as const
          ).map(([key, icon, label]) => (
            <button
              key={key}
              className={`nav-item${section === key ? " active" : ""}`}
              onClick={() => {
                setSection(key);
                setSidebarOpen(false);
              }}
            >
              {icon} {label}
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          <button className="account" title="Model tier & access token" onClick={() => setShowToken((v) => !v)}>
            <span className="status-dot"></span>
            <span>
              {activeTier || "Connecting…"}
              <small>Signed in</small>
            </span>
          </button>
          {showToken && (
            <input
              className="search"
              type="password"
              placeholder="Access token (private mode)"
              value={token}
              onChange={(e) => {
                setToken(e.target.value);
                localStorage.setItem("poka_token", e.target.value);
              }}
            />
          )}
          <div className="ghost-row">
            <button className="ghost-btn" onClick={exportChat}>
              Export chat
            </button>
            <button
              className="ghost-btn"
              onClick={async () => {
                await api.deleteAllArtifacts();
                setArtifacts(await api.artifacts());
              }}
            >
              Clear old files
            </button>
          </div>
        </div>
      </aside>
      {sidebarOpen && (
        <div className="drawer-backdrop" onClick={() => setSidebarOpen(false)} />
      )}

      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-btn hamburger"
              title="Menu"
              onClick={() => setSidebarOpen((v) => !v)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="4" x2="20" y1="6" y2="6" /><line x1="4" x2="20" y1="12" y2="12" /><line x1="4" x2="20" y1="18" y2="18" /></svg>
            </button>
            {section !== null && (
              <button className="icon-btn" title="Back to chat" onClick={() => setSection(null)}>
                {I.back}
              </button>
            )}
            <div className="chat-title">
              {section ? SECTION_TITLES[section].title : chatTitle}
            </div>
          </div>
          <div className="model-pill-wrap">
            <button className="model-pill" onClick={() => setTierMenu((v) => !v)} title="Model tier">
              <span className="dot"></span> {activeTier || "…"} <span>▾</span>
            </button>
            {tierMenu && (
              <div className="pop-menu" style={{ right: 0, top: "calc(100% + 8px)" }}>
                {allTiers.map((t) => (
                  <button
                    key={t}
                    className={t === activeTier ? "picked" : ""}
                    onClick={() => {
                      setActiveTier(t);
                      setTierMenu(false);
                    }}
                  >
                    {t === activeTier ? "● " : "○ "} {t}
                    {tiers.includes(t) ? "" : " (no key)"}
                  </button>
                ))}
              </div>
            )}
          </div>
        </header>

        {section === null ? (
          <div className="view">
            <div className="chat-scroll">
              <div className="chat-col">
                {messages.length > 0 && <div className="divider">{dayLabel(messages[0].time)}</div>}
                {messages.length === 0 && !sending && (
                  <div className="empty-state">
                    <div className="empty-icon">
                      <BugIcon size={26} />
                    </div>
                    Start a new conversation…
                  </div>
                )}
                {messages.map((m, i) =>
                  m.role === "user" ? (
                    <div className="msg user" key={i}>
                      <div className="col">
                        {(m.attachments || []).map((a) => (
                          <span className="msg-file" key={a.id}>
                            {a.kind}: {a.name}
                          </span>
                        ))}
                        <div className="bubble">
                          <ReactMarkdown>{m.content}</ReactMarkdown>
                        </div>
                        <div className="meta">
                          <span>{fmtTime(m.time)}</span>
                          <button
                            onClick={(e) => {
                              const b = e.currentTarget;
                              copyText(m.content, () => {
                                b.textContent = "Copied";
                                setTimeout(() => (b.textContent = "Copy"), 1200);
                              });
                            }}
                          >
                            Copy
                          </button>
                          <button onClick={() => truncateAndEdit(i, m.content)}>Edit</button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="msg ai" key={i}>
                      <div className="avatar">
                      <BugIcon size={13} />
                    </div>
                      <div className="col">
                        <div className="bubble">
                          {m.attachments
                            ?.filter((a) => a.kind !== "pdf" && a.kind !== "csv")
                            .map((a) => (
                              <img
                                key={a.id}
                                className="msg-img"
                                src={`/api/uploads/${a.id}/file`}
                                alt={a.name}
                              />
                            ))}
                          {m.content ? (
                            <ReactMarkdown>{m.content}</ReactMarkdown>
                          ) : (
                            <span className="thinking-dots">
                              <span></span>
                              <span></span>
                              <span></span>
                            </span>
                          )}
                          {sending && i === messages.length - 1 && !!m.content && (
                            <span className="stream-cursor">▍</span>
                          )}
                        </div>
                        {(m.sources || []).length > 0 && (
                          <div style={{ marginTop: 8, fontSize: 13 }}>
                            {(m.sources || []).map((s, k) => (
                              <p key={k} style={{ margin: "2px 0", color: "var(--text-dim)" }}>
                                <span>[{k + 1}]</span>{" "}
                                <a
                                  href={s.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{ color: "var(--accent)" }}
                                >
                                  {s.title || s.domain}
                                </a>
                              </p>
                            ))}
                          </div>
                        )}
                        {(m.artifacts || []).map((a) => (
                          <div className="card" key={a.id} style={{ marginTop: 8 }}>
                            <div className="tile">{I.doc}</div>
                            <div className="grow">
                              <div className="title">{a.name}</div>
                            </div>
                            <a
                              className="card-icon-btn"
                              style={{ opacity: 1 }}
                              title="Download"
                              href={`/api/artifacts/${a.id}/download`}
                              download
                            >
                              {I.down}
                            </a>
                          </div>
                        ))}
                        <div className="meta">
                          <span>
                            {[fmtTime(m.time), m.model, m.search_executed ? "Web search" : ""]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                          <button
                            onClick={(e) => {
                              const b = e.currentTarget;
                              copyText(m.content, () => {
                                b.textContent = "Copied";
                                setTimeout(() => (b.textContent = "Copy"), 1200);
                              });
                            }}
                          >
                            Copy
                          </button>
                          <button onClick={() => regenerate(i)}>Regenerate</button>
                          {!!m.sources?.length && !!m.search_executed && (
                            <button
                              onClick={async () => {
                                try {
                                  await api.saveBrief(i, activeProject);
                                  setBriefs(await api.briefs());
                                } catch (e: any) {
                                  setError(e.message || "Could not save brief.");
                                }
                              }}
                            >
                              Save as brief
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  ),
                )}
                {thinking && messages[messages.length - 1]?.role === "user" && (
                  <div className="msg ai">
                    <div className="avatar">
                      <BugIcon size={13} />
                    </div>
                    <div className="col">
                      <div className="bubble thinking-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            </div>

            {error && (
              <div style={{ padding: "0 24px" }}>
                <div className="error-bar">
                  <span>{error}</span>
                  <button onClick={() => setError("")}>×</button>
                </div>
              </div>
            )}

            <div className="composer-wrap">
              <div
                className={`composer${deepMode ? " deep" : ""}`}
                id="composer"
                ref={composerRef}
                onDragEnter={(e) => {
                  e.preventDefault();
                  composerRef.current?.classList.add("dragover");
                }}
                onDragOver={(e) => e.preventDefault()}
                onDragLeave={() => composerRef.current?.classList.remove("dragover")}
                onDrop={(e) => {
                  e.preventDefault();
                  composerRef.current?.classList.remove("dragover");
                  if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
                }}
              >
                <div className="attachments">
                  {pending.map((p) => {
                    const isImage = p.kind !== "pdf" && p.kind !== "csv";
                    const meta = extMeta(p.name);
                    return (
                      <div className="chip" key={p.id}>
                        {isImage && p.preview ? (
                          <img className="thumb" src={p.preview} alt="" />
                        ) : (
                          <span
                            className="ext"
                            style={{ background: meta.color + "22", color: meta.color }}
                          >
                            {meta.label}
                          </span>
                        )}
                        <span className="fname" title={p.name}>
                          {p.name}
                        </span>
                        <span className="fsize">{fmtSize(p.size)}</span>
                        <button
                          className="chip-x"
                          title="Remove"
                          onClick={() => {
                            if (p.preview) URL.revokeObjectURL(p.preview);
                            setPending((l) => l.filter((x) => x.id !== p.id));
                          }}
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })}
                </div>
                <textarea
                  ref={textareaRef}
                  rows={1}
                  placeholder={placeholder}
                  value={input}
                  disabled={sending}
                  onChange={(e) => {
                    setInput(e.target.value);
                    autosize();
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                />
                <div className="composer-bottom">
                  <div
                    className="mode-toggle"
                    ref={toggleRef}
                    data-mode={deepMode ? "deep" : "fast"}
                    role="tablist"
                    aria-label="Response mode"
                  >
                    <div className="mode-thumb" ref={thumbRef} aria-hidden="true"></div>
                    <button
                      className={`mode-btn${!deepMode ? " active" : ""}`}
                      role="tab"
                      aria-selected={!deepMode}
                      aria-label="Fast mode"
                      title="Quick answers — Alt+M to switch"
                      onClick={() => setDeepMode(false)}
                    >
                      {I.bolt}
                    </button>
                    <button
                      className={`mode-btn${deepMode ? " active" : ""}`}
                      role="tab"
                      aria-selected={deepMode}
                      aria-label="Deep mode"
                      title="Thorough answers — Alt+M to switch"
                      onClick={() => setDeepMode(true)}
                    >
                      {I.brain}
                    </button>
                  </div>

                  <button
                    className={`web-btn${forceSearch ? " active" : ""}`}
                    aria-pressed={forceSearch}
                    title="Search the web — Alt+S to toggle"
                    onClick={() => setForceSearch((v) => !v)}
                  >
                    {I.globe} Search
                  </button>

                  <div className="spacer"></div>

                  <div className="attach-wrap">
                    <button
                      className="icon-btn"
                      title="Attach"
                      onClick={() => setAttachOpen((v) => !v)}
                    >
                      {I.clip}
                    </button>
                    <div className={`attach-menu${attachOpen ? " open" : ""}`}>
                      <button
                        className="attach-opt"
                        onClick={() => {
                          setAttachOpen(false);
                          openCamera();
                        }}
                      >
                        <span className="tile">{I.camera}</span> Camera
                        <small>take a photo</small>
                      </button>
                      <button
                        className="attach-opt"
                        onClick={() => {
                          setAttachOpen(false);
                          photoRef.current?.click();
                        }}
                      >
                        <span className="tile">{I.photo}</span> Photos
                        <small>images</small>
                      </button>
                      <button
                        className="attach-opt"
                        onClick={() => {
                          setAttachOpen(false);
                          docRef.current?.click();
                        }}
                      >
                        <span className="tile">{I.doc}</span> Files
                        <small>pdf · csv · images</small>
                      </button>
                    </div>
                  </div>

                  {sending ? (
                    <button
                      className="btn-send"
                      title="Stop"
                      onClick={() => abortRef.current?.abort()}
                    >
                      ■
                    </button>
                  ) : (
                    <button className="btn-send" title="Send" onClick={send}>
                      {I.send}
                    </button>
                  )}
                </div>

                <input
                  type="file"
                  ref={photoRef}
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => {
                    if (e.target.files) uploadFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
                <input
                  type="file"
                  ref={docRef}
                  multiple
                  hidden
                  onChange={(e) => {
                    if (e.target.files) uploadFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
              </div>
              <div className="disclaimer">
                Poka can make mistakes. Consider checking important information.
              </div>
            </div>
          </div>
        ) : (
          <div className="view">
            <div className="panel-scroll">
              <div className="panel-col">
                <PanelBody
                  section={section}
                  briefs={briefs}
                  setBriefs={setBriefs}
                  facts={facts}
                  setFacts={setFacts}
                  uploads={uploads}
                  artifacts={artifacts}
                  setArtifacts={setArtifacts}
                  messages={messages}
                  chats={chats}
                  researchFilter={researchFilter}
                  setResearchFilter={setResearchFilter}
                  setError={setError}
                  activeProject={activeProject}
                />
              </div>
            </div>
          </div>
        )}
      </main>

      {camOpen && (
        <div className="modal-backdrop" onClick={closeCamera}>
          <div className="camera-box" onClick={(e) => e.stopPropagation()}>
            <div className="cam-title">Take a photo</div>
            <div className="cam-stage">
              {!shotTaken && !camError && <video ref={videoRef} autoPlay playsInline muted />}
              <canvas ref={canvasRef} className={shotTaken ? "" : "hidden"} />
              {camError && <div className="cam-error">{camError}</div>}
            </div>
            <div className="cam-actions">
              <button className="cam-btn ghost" onClick={closeCamera}>
                Cancel
              </button>
              {shotTaken ? (
                <>
                  <button
                    className="cam-btn ghost"
                    onClick={() => {
                      setShotTaken(false);
                    }}
                  >
                    Retake
                  </button>
                  <button className="cam-btn primary" onClick={useShot}>
                    {I.check} Use photo
                  </button>
                </>
              ) : (
                <button className="cam-btn primary" onClick={captureShot} disabled={!!camError}>
                  {I.camera} Capture
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- section panels (live data only) ---------------- */
function PanelBody(props: {
  section: Section;
  briefs: any[];
  setBriefs: (v: any[]) => void;
  facts: any[];
  setFacts: (v: any[]) => void;
  uploads: { id: string; kind: string; name: string }[];
  artifacts: { id: string; kind: string; name: string }[];
  setArtifacts: (v: { id: string; kind: string; name: string }[]) => void;
  messages: ChatMessage[];
  chats: any[];
  researchFilter: string;
  setResearchFilter: (v: string) => void;
  setError: (v: string) => void;
  activeProject: string | null;
}) {
  const {
    section,
    briefs,
    setBriefs,
    facts,
    setFacts,
    uploads,
    artifacts,
    setArtifacts,
    messages,
    chats,
    researchFilter,
    setResearchFilter,
    setError,
  } = props;

  if (section === "research") {
    const q = researchFilter.toLowerCase();
    const list = briefs.filter((b) => String(b.query || "").toLowerCase().includes(q));
    return (
      <>
        <div className="panel-head">
          <h2>Research</h2>
          <p>Saved research reports. Save any search-backed answer as a brief from the chat.</p>
        </div>
        <input
          className="panel-input"
          type="text"
          placeholder="Filter research…"
          value={researchFilter}
          onChange={(e) => setResearchFilter(e.target.value)}
        />
        <div className="card-list">
          {list.length === 0 && <p className="empty-note">No saved research yet.</p>}
          {list.map((b) => (
            <div className="card" key={b.id}>
              <div className="tile">{I.flask}</div>
              <div className="grow">
                <div className="title">{b.query || b.id}</div>
                <div className="sub">
                  {(b.sources || []).length} sources
                  {b.created ? ` · ${dayLabel(b.created)}` : ""}
                </div>
              </div>
              <span className="badge ok">Saved</span>
              <button
                className="card-icon-btn"
                title="Generate Word doc"
                onClick={async () => {
                  await api.briefDocx(b.id);
                  setArtifacts(await api.artifacts());
                }}
              >
                {I.doc}
              </button>
              <button
                className="card-x"
                title="Delete"
                onClick={async () => {
                  await api.deleteBrief(b.id);
                  setBriefs(await api.briefs());
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </>
    );
  }

  if (section === "memory") {
    return (
      <>
        <div className="panel-head">
          <h2>Memory</h2>
          <p>Things Poka remembers across conversations. Hover a card to forget it.</p>
        </div>
        <div className="card-list">
          {facts.length === 0 && <p className="empty-note">Nothing remembered yet.</p>}
          {facts.map((f: any, i: number) => (
            <div className="card" key={i}>
              <div className="tile">{I.memory}</div>
              <div className="grow">
                <div className="title">{f.value || JSON.stringify(f)}</div>
              </div>
              <button
                className="card-x"
                title="Forget"
                onClick={async () => {
                  try {
                    await api.deleteFact(String(f.ref || f.id || f.value));
                    setFacts(await api.facts());
                  } catch (e: any) {
                    setError(e.message || "Could not forget.");
                  }
                }}
              >
                ✕ Forget
              </button>
            </div>
          ))}
        </div>
      </>
    );
  }

  if (section === "files") {
    return (
      <>
        <div className="panel-head">
          <h2>Files</h2>
          <p>Documents shared in this workspace.</p>
        </div>
        <div className="card-list">
          {uploads.length === 0 && <p className="empty-note">No files uploaded yet.</p>}
          {uploads.map((f) => (
            <div className="card" key={f.id}>
              <div className="tile">{I.doc}</div>
              <div className="grow">
                <div className="title">{f.name}</div>
                <div className="sub">{f.kind}</div>
              </div>
              <a
                className="card-icon-btn"
                style={{ opacity: 1 }}
                title="Download"
                href={`/api/uploads/${f.id}/file`}
                download
              >
                {I.down}
              </a>
            </div>
          ))}
        </div>
      </>
    );
  }

  if (section === "artifacts") {
    return (
      <>
        <div className="panel-head">
          <h2>Artifacts</h2>
          <p>Generated documents, code, and visuals.</p>
        </div>
        <div className="art-grid">
          {artifacts.length === 0 && <p className="empty-note">No artifacts yet.</p>}
          {artifacts.map((a) => {
            const st = artStyle(a.kind);
            return (
              <div
                className="art"
                key={a.id}
                title={`${a.name} — click to download`}
                onClick={() => {
                  const link = document.createElement("a");
                  link.href = `/api/artifacts/${a.id}/download`;
                  link.download = a.name;
                  link.click();
                }}
              >
                <div className="art-thumb" style={{ background: st.g }}>
                  {st.e}
                </div>
                <div className="art-body">
                  <div className="art-title">{a.name}</div>
                  <div className="art-sub">{a.kind}</div>
                </div>
                <div className="art-actions">
                  <button
                    title="Regenerate"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await api.regenerateArtifact(a.id);
                      setArtifacts(await api.artifacts());
                    }}
                  >
                    Regenerate
                  </button>
                  <button
                    className="danger"
                    title="Delete"
                    onClick={async (e) => {
                      e.stopPropagation();
                      await api.deleteArtifact(a.id);
                      setArtifacts(await api.artifacts());
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </>
    );
  }

  if (section === "sources") {
    const seen = new Set<string>();
    const all: { title: string; url: string; domain: string }[] = [];
    const push = (s: any) => {
      const url = String(s?.url || "");
      if (!url || seen.has(url)) return;
      seen.add(url);
      all.push({
        title: String(s?.title || s?.domain || url),
        url,
        domain: String(s?.domain || ""),
      });
    };
    briefs.forEach((b) => (b.sources || []).forEach(push));
    messages.forEach((m) => (m.sources || []).forEach(push));
    return (
      <>
        <div className="panel-head">
          <h2>Sources</h2>
          <p>Cited sources from briefs and the open conversation.</p>
        </div>
        <div className="card-list">
          {all.length === 0 && <p className="empty-note">No cited sources yet.</p>}
          {all.map((s) => (
            <div className="card" key={s.url}>
              <div className="tile letter">{(s.title[0] || "?").toUpperCase()}</div>
              <div className="grow">
                <div className="title">{s.title}</div>
                <div className="sub">{s.domain}</div>
              </div>
              <a className="card-icon-btn" style={{ opacity: 1 }} title="Open source" href={s.url} target="_blank" rel="noopener noreferrer">
                {I.open}
              </a>
            </div>
          ))}
        </div>
      </>
    );
  }

  /* stats — computed from real data, never hardcoded */
  const allMsgs: ChatMessage[] = [
    ...messages,
    ...chats.flatMap((c) => (Array.isArray(c.messages) ? c.messages : [])),
  ];
  const days: { label: string; count: number }[] = [];
  for (let back = 6; back >= 0; back--) {
    const d = new Date();
    d.setDate(d.getDate() - back);
    const key = d.toDateString();
    const count = allMsgs.filter((m) => {
      if (!m.time) return false;
      return new Date(m.time).toDateString() === key;
    }).length;
    days.push({
      label: d.toLocaleDateString(undefined, { weekday: "short" }),
      count,
    });
  }
  const max = Math.max(1, ...days.map((d) => d.count));
  return (
    <>
      <div className="panel-head">
        <h2>Stats</h2>
        <p>Your usage over the last 7 days.</p>
      </div>
      <div className="stat-grid">
        <div className="stat">
          <div className="num">{allMsgs.length}</div>
          <div className="lbl">Messages</div>
        </div>
        <div className="stat">
          <div className="num">{chats.length + (messages.length ? 1 : 0)}</div>
          <div className="lbl">Chats</div>
        </div>
        <div className="stat">
          <div className="num">{artifacts.length}</div>
          <div className="lbl">Artifacts</div>
        </div>
        <div className="stat">
          <div className="num">{briefs.length}</div>
          <div className="lbl">Briefs</div>
        </div>
      </div>
      <div className="chart-box">
        <div className="chart-title">Messages per day</div>
        <div className="bars">
          {days.map((d, i) => (
            <div
              key={i}
              className="bar"
              style={{ height: `${Math.max(3, Math.round((d.count / max) * 100))}%` }}
              title={`${d.count} messages`}
            />
          ))}
        </div>
        <div className="bar-labels">
          {days.map((d, i) => (
            <div key={i}>{d.label}</div>
          ))}
        </div>
      </div>
    </>
  );
}

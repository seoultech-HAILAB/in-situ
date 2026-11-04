"use client";

type Auth = { id: string; token: string };
type Entry = { id: string; label: string; client_at: string; sequence: number; page_id: string; data: Record<string, unknown>; context: Record<string, unknown> };
let auth: Auth | null = null;
let context: Record<string, unknown> = {};
let pageId = "";
let sequence = 0;
let flushing = false;
const queue = new Map<string, Entry>();
const writes = new Map<string, Promise<void>>();
let database: Promise<IDBDatabase> | null = null;

// LAN HTTP pages also work; randomUUID itself requires a secure context.
export function newEventId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function studyHeaders(): Record<string, string> {
  return auth ? { "X-Study-Id": auth.id, "X-Study-Token": auth.token } : {};
}

function db() {
  return database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open("trace-study-events", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("events", { keyPath: "key" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function persist(id: string, entry?: Entry, experimentId = auth!.id) {
  const store = await db();
  await new Promise<void>((resolve, reject) => {
    const transaction = store.transaction("events", "readwrite");
    const rows = transaction.objectStore("events");
    const key = `${experimentId}:${id}`;
    if (entry) rows.put({ key, experiment_id: experimentId, entry }); else rows.delete(key);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
}

export function studyContext(value: Record<string, unknown>) { context = { ...context, ...value }; }

export function logStudy(label: string, data: Record<string, unknown> = {}) {
  if (!auth) return;
  const entry: Entry = { id: newEventId(), label, client_at: new Date().toISOString(), sequence: ++sequence, page_id: pageId,
    data, context: { ...context, monotonic_ms: performance.now(), visibility: document.visibilityState } };
  queue.set(entry.id, entry);
  const write = persist(entry.id, entry).catch(() => { /* Memory queue continues; retry persistence at flush. */ });
  writes.set(entry.id, write);
}

export async function flushStudy(keepalive = false) {
  if (!auth || flushing || !queue.size) return;
  const sending = auth;
  flushing = true;
  try {
    // Stay below the browser's shared 64 KiB keepalive budget, even with drafts.
    const entries: Entry[] = [];
    let bytes = 20;
    for (const entry of queue.values()) {
      const size = new TextEncoder().encode(JSON.stringify(entry)).length + 1;
      if (entries.length && (bytes + size > 45000 || entries.length >= 100)) break;
      entries.push(entry); bytes += size;
    }
    await Promise.all(entries.map(entry => writes.get(entry.id)));
    const res = await fetch(`/api/experiments/${sending.id}/events`, { method: "POST", keepalive,
      headers: { "Content-Type": "application/json", "X-Study-Id":sending.id, "X-Study-Token":sending.token }, body: JSON.stringify({ events: entries }) });
    if (!res.ok) throw new Error("로그 저장 대기 중");
    const result = await res.json();
    for (const id of result.accepted) { if (auth?.id===sending.id) { queue.delete(id); writes.delete(id); } await persist(id,undefined,sending.id).catch(() => {}); }
  } catch { /* Durable outbox retries on reconnect/reload. Never discard unacknowledged records. */ }
  finally { flushing = false; }
}

export async function connectStudy(value: Auth) {
  if (auth && auth.id!==value.id) {
    let previousSize=Infinity;
    while (queue.size && queue.size<previousSize) { previousSize=queue.size; await flushStudy(); }
    queue.clear(); writes.clear(); context={}; sequence=0;
  }
  auth = value;
  pageId = newEventId();
  try {
    const store = await db();
    const rows = await new Promise<Array<{ experiment_id: string; entry: Entry }>>((resolve, reject) => {
      const req = store.transaction("events").objectStore("events").getAll();
      req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
    });
    for (const row of rows) if (row.experiment_id === auth.id) queue.set(row.entry.id, row.entry);
  } catch { /* Browsers without persistent storage still send live records. */ }
}

function elementInfo(target: EventTarget | null) {
  const node = target instanceof Element ? target : null;
  const el = node?.closest<HTMLElement>("button,select,textarea,input,[role=separator],[role=dialog],[role=region]") ?? node;
  return { tag: el?.tagName, role: el?.getAttribute("role"), label: el?.getAttribute("aria-label") ?? el?.getAttribute("title"),
    text: el?.matches("button") ? el.textContent?.trim().slice(0, 180) : undefined,
    class: typeof el?.className === "string" ? el.className.slice(0, 200) : undefined };
}

export function observeStudy() {
  const cleanups: Array<() => void> = [];
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const on = (target: EventTarget, name: string, fn: (event: Event) => void) => {
    target.addEventListener(name, fn, true); cleanups.push(() => target.removeEventListener(name, fn, true));
  };
  const debounce = (key: string, fn: () => void, ms: number) => {
    clearTimeout(timers.get(key)); timers.set(key, setTimeout(fn, ms));
  };
  let lastPointer = 0;
  let lastActivity = performance.now();
  const observed = new Set<Element>();
  const visible = new Map<Element, { started: number; context: Record<string, unknown>; details: Record<string, unknown> }>();
  const hideExplanation = (el: Element, reason: string) => {
    const entry = visible.get(el);
    if (!entry) return;
    logStudy("explanation.hidden", { ...entry.details, viewed_context: entry.context, reason, duration_ms: performance.now() - entry.started });
    visible.delete(el);
  };
  const intersection = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting && !document.hidden && !visible.has(entry.target)) {
        const details = { transformation_id: entry.target.getAttribute("data-transformation-id"),
          code_start: entry.target.getAttribute("data-code-start"), code_end: entry.target.getAttribute("data-code-end"),
          surface: entry.target.closest(".transformation-bubble") ? "in-situ-bubble" : "ex-situ-explanation",
          intersection_ratio: entry.intersectionRatio };
        visible.set(entry.target, { started: performance.now(), context: { ...context }, details });
        logStudy("explanation.visible", details);
      } else if (!entry.isIntersecting) hideExplanation(entry.target, "outside_viewport");
    }
  });
  const updateObserved = () => {
    for (const el of observed) if (!el.isConnected) { hideExplanation(el, "removed"); intersection.unobserve(el); observed.delete(el); }
    for (const el of document.querySelectorAll(".transformation-operation")) if (!observed.has(el)) { observed.add(el); intersection.observe(el); }
  };
  const mutations = new MutationObserver(updateObserved);
  mutations.observe(document.body, { childList: true, subtree: true });
  updateObserved();
  on(document, "click", event => { lastActivity = performance.now(); const e = event as MouseEvent;
    logStudy("ui.click", { ...elementInfo(e.target), x: e.clientX, y: e.clientY, button: e.button }); });
  on(document, "pointermove", event => { const e = event as PointerEvent;
    lastActivity = performance.now();
    if (performance.now() - lastPointer < 500) return; lastPointer = performance.now();
    logStudy("ui.pointer", { ...elementInfo(e.target), x: e.clientX, y: e.clientY, pointer_type: e.pointerType }); });
  on(document, "input", event => { lastActivity = performance.now(); const el = event.target;
    if (el instanceof HTMLInputElement && el.type === "password") return;
    if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement || el instanceof HTMLSelectElement) {
      // Every app input value is recorded; no OS-wide keystroke/clipboard access.
      logStudy("ui.input", { ...elementInfo(el), value: el.value.slice(0, 10000), selection_start: "selectionStart" in el ? el.selectionStart : null });
    } });
  on(document, "keydown", event => { const e = event as KeyboardEvent; lastActivity = performance.now();
    if (["Enter", "Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End"].includes(e.key))
      logStudy("ui.key", { ...elementInfo(e.target), key: e.key, ctrl: e.ctrlKey, shift: e.shiftKey, alt: e.altKey, meta: e.metaKey, composing: e.isComposing }); });
  for (const name of ["focusin", "focusout"]) on(document, name, event => logStudy(name === "focusin" ? "ui.focus" : "ui.blur", elementInfo(event.target)));
  on(document, "scroll", event => { lastActivity = performance.now(); const el = event.target;
    if (el instanceof Element) debounce(`scroll:${el.className}`, () => logStudy("ui.scroll", { ...elementInfo(el), top: el.scrollTop, left: el.scrollLeft,
      height: el.scrollHeight, width: el.scrollWidth, viewport_height: el.clientHeight, viewport_width: el.clientWidth }), 180); });
  on(document, "selectionchange", () => debounce("selection", () => { const selection = getSelection(); if (selection?.toString())
    logStudy("ui.selection", { ...elementInfo(selection.anchorNode?.parentElement ?? null), text: selection.toString().slice(0, 10000) }); }, 300));
  for (const name of ["copy", "paste"]) on(document, name, event => logStudy(`ui.${name}`, { ...elementInfo(event.target),
    text: (name === "copy" ? getSelection()?.toString() : (event as ClipboardEvent).clipboardData?.getData("text/plain"))?.slice(0, 10000) }));
  on(window, "resize", () => debounce("resize", () => logStudy("ui.resize", { width: innerWidth, height: innerHeight, ratio: devicePixelRatio }), 200));
  on(document, "visibilitychange", () => {
    if (document.hidden) for (const el of visible.keys()) hideExplanation(el, "document_hidden");
    else for (const el of observed) { intersection.unobserve(el); intersection.observe(el); }
    logStudy("page.visibility", { state: document.visibilityState }); void flushStudy(document.hidden);
  });
  for (const name of ["focus", "blur"]) on(window, name, event => { if (event.target === window) logStudy(`page.${name}`); });
  for (const name of ["online", "offline"]) on(window, name, () => { logStudy(`network.${name}`); if (name === "online") void flushStudy(); });
  on(window, "pagehide", event => { logStudy("page.hide", { persisted: (event as PageTransitionEvent).persisted }); void flushStudy(true); });
  on(window, "error", event => { const e = event as ErrorEvent; logStudy("client.error", { message: e.message, file: e.filename, line: e.lineno, column: e.colno, stack: e.error?.stack?.slice(0, 6000) }); });
  on(window, "unhandledrejection", event => logStudy("client.rejection", { message: String((event as PromiseRejectionEvent).reason).slice(0, 6000) }));
  const flush = setInterval(() => void flushStudy(), 2000);
  const heartbeat = setInterval(() => logStudy("page.heartbeat", { online: navigator.onLine, idle_ms: Math.round(performance.now() - lastActivity),
    width: innerWidth, height: innerHeight, unsent_events: queue.size }), 15000);
  logStudy("page.enter", { path: location.pathname, navigation: performance.getEntriesByType("navigation").map(e => (e as PerformanceNavigationTiming).type) });
  return () => { for (const el of visible.keys()) hideExplanation(el, "observer_stopped"); intersection.disconnect(); mutations.disconnect(); cleanups.forEach(fn => fn()); timers.forEach(clearTimeout); clearInterval(flush); clearInterval(heartbeat); void flushStudy(true); };
}

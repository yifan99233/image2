import type { AgentDocument } from "@/services/prompt";

/** One conversational turn / event inside an Agent session. */
export type AgentSessionMessage = {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  createdAt: string;
  kind?: "intent" | "plan" | "stats" | "notice" | "confirm" | "error";
  meta?: {
    planIntent?: string;
    promptCount?: number;
    taskIds?: number[];
  };
};

/**
 * Isolated Agent workspace.
 * Context, documents, focus, and linked generation tasks must stay inside this session.
 */
export type AgentSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: AgentSessionMessage[];
  /** Recent user intents for this session only (fed into planning context). */
  recentIntents: string[];
  documents: AgentDocument[];
  focusTaskId: number | null;
  /** Task ids created / bound while this session was active. */
  taskIds: number[];
  textModelId: number | null;
  styleKitIds: string[];
  lastPlanSummary?: string | null;
  /** Unsent composer draft for this session only. */
  draftPrompt?: string;
};

export type AgentSessionStore = {
  version: 1;
  activeId: string;
  sessions: AgentSession[];
};

export const AGENT_SESSIONS_STORAGE_KEY = "imagine.agent.sessions.v1";
export const MAX_AGENT_SESSIONS = 16;
export const MAX_SESSION_MESSAGES = 48;
export const MAX_SESSION_DOCUMENTS = 5;
export const MAX_DOC_CHARS = 80_000;
export const MAX_SESSION_TASK_IDS = 200;

const uid = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;

export const createEmptySession = (partial?: Partial<AgentSession>): AgentSession => {
  const now = new Date().toISOString();
  return {
    id: partial?.id || uid(),
    title: partial?.title || "新会话",
    createdAt: partial?.createdAt || now,
    updatedAt: partial?.updatedAt || now,
    messages: partial?.messages || [],
    recentIntents: partial?.recentIntents || [],
    documents: (partial?.documents || []).slice(0, MAX_SESSION_DOCUMENTS),
    focusTaskId: partial?.focusTaskId ?? null,
    taskIds: partial?.taskIds || [],
    textModelId: partial?.textModelId ?? null,
    styleKitIds: partial?.styleKitIds || [],
    lastPlanSummary: partial?.lastPlanSummary ?? null,
    draftPrompt: typeof partial?.draftPrompt === "string" ? partial.draftPrompt.slice(0, 8000) : "",
  };
};

const clampDocuments = (docs: AgentDocument[]): AgentDocument[] =>
  docs.slice(0, MAX_SESSION_DOCUMENTS).map((doc) => ({
    ...doc,
    text: (doc.text || "").slice(0, MAX_DOC_CHARS),
    char_count: Math.min(Number(doc.char_count) || (doc.text || "").length, MAX_DOC_CHARS),
  }));

export const normalizeSession = (raw: Partial<AgentSession> | null | undefined): AgentSession | null => {
  if (!raw || typeof raw !== "object") return null;
  const id = typeof raw.id === "string" && raw.id ? raw.id : uid();
  const messages = Array.isArray(raw.messages)
    ? raw.messages
        .filter((m): m is AgentSessionMessage => Boolean(m && typeof m === "object" && typeof (m as AgentSessionMessage).content === "string"))
        .slice(-MAX_SESSION_MESSAGES)
        .map((m): AgentSessionMessage => ({
          id: typeof m.id === "string" ? m.id : uid(),
          role: m.role === "agent" || m.role === "system" ? m.role : "user",
          content: String(m.content || "").slice(0, 4000),
          createdAt: typeof m.createdAt === "string" ? m.createdAt : new Date().toISOString(),
          kind: m.kind,
          meta: m.meta,
        }))
    : [];

  return createEmptySession({
    id,
    title: typeof raw.title === "string" && raw.title.trim() ? raw.title.trim().slice(0, 40) : "未命名会话",
    createdAt: typeof raw.createdAt === "string" ? raw.createdAt : new Date().toISOString(),
    updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt : new Date().toISOString(),
    messages,
    recentIntents: Array.isArray(raw.recentIntents)
      ? raw.recentIntents.filter((x): x is string => typeof x === "string").map((x) => x.slice(0, 500)).slice(-8)
      : [],
    documents: clampDocuments(Array.isArray(raw.documents) ? (raw.documents as AgentDocument[]) : []),
    focusTaskId: typeof raw.focusTaskId === "number" ? raw.focusTaskId : null,
    taskIds: Array.isArray(raw.taskIds)
      ? raw.taskIds.filter((n): n is number => typeof n === "number" && Number.isFinite(n)).slice(-MAX_SESSION_TASK_IDS)
      : [],
    textModelId: typeof raw.textModelId === "number" ? raw.textModelId : null,
    styleKitIds: Array.isArray(raw.styleKitIds)
      ? raw.styleKitIds.filter((x): x is string => typeof x === "string").slice(0, 4)
      : [],
    lastPlanSummary: typeof raw.lastPlanSummary === "string" ? raw.lastPlanSummary.slice(0, 500) : null,
    draftPrompt: typeof raw.draftPrompt === "string" ? raw.draftPrompt.slice(0, 8000) : "",
  });
};

export const loadAgentSessionStore = (): AgentSessionStore => {
  try {
    const raw = localStorage.getItem(AGENT_SESSIONS_STORAGE_KEY);
    if (!raw) {
      const session = createEmptySession({ title: "会话 1" });
      return { version: 1, activeId: session.id, sessions: [session] };
    }
    const parsed = JSON.parse(raw) as Partial<AgentSessionStore>;
    const sessions = (Array.isArray(parsed.sessions) ? parsed.sessions : [])
      .map((item) => normalizeSession(item))
      .filter((item): item is AgentSession => Boolean(item))
      .slice(0, MAX_AGENT_SESSIONS);
    if (!sessions.length) {
      const session = createEmptySession({ title: "会话 1" });
      return { version: 1, activeId: session.id, sessions: [session] };
    }
    const activeId =
      typeof parsed.activeId === "string" && sessions.some((s) => s.id === parsed.activeId)
        ? parsed.activeId
        : sessions[0].id;
    return { version: 1, activeId, sessions };
  } catch {
    const session = createEmptySession({ title: "会话 1" });
    return { version: 1, activeId: session.id, sessions: [session] };
  }
};

export const saveAgentSessionStore = (store: AgentSessionStore) => {
  try {
    const payload: AgentSessionStore = {
      version: 1,
      activeId: store.activeId,
      sessions: store.sessions.slice(0, MAX_AGENT_SESSIONS).map((s) => normalizeSession(s)!).filter(Boolean),
    };
    localStorage.setItem(AGENT_SESSIONS_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // quota / private mode
  }
};

export const getActiveSession = (store: AgentSessionStore): AgentSession => {
  return store.sessions.find((s) => s.id === store.activeId) || store.sessions[0] || createEmptySession();
};

export const upsertSession = (store: AgentSessionStore, session: AgentSession): AgentSessionStore => {
  const next = normalizeSession({ ...session, updatedAt: new Date().toISOString() })!;
  const exists = store.sessions.some((s) => s.id === next.id);
  const sessions = exists
    ? store.sessions.map((s) => (s.id === next.id ? next : s))
    : [next, ...store.sessions].slice(0, MAX_AGENT_SESSIONS);
  return { ...store, sessions, activeId: next.id };
};

export const createAndActivateSession = (
  store: AgentSessionStore,
  title?: string,
): { store: AgentSessionStore; session: AgentSession } => {
  const count = store.sessions.length + 1;
  const session = createEmptySession({ title: title?.trim() || `会话 ${count}` });
  const sessions = [session, ...store.sessions].slice(0, MAX_AGENT_SESSIONS);
  return { store: { version: 1, activeId: session.id, sessions }, session };
};

export const deleteSession = (store: AgentSessionStore, sessionId: string): AgentSessionStore => {
  const sessions = store.sessions.filter((s) => s.id !== sessionId);
  if (!sessions.length) {
    const session = createEmptySession({ title: "会话 1" });
    return { version: 1, activeId: session.id, sessions: [session] };
  }
  const activeId = store.activeId === sessionId ? sessions[0].id : store.activeId;
  return { version: 1, activeId, sessions };
};

export const renameSession = (store: AgentSessionStore, sessionId: string, title: string): AgentSessionStore => {
  const nextTitle = title.trim().slice(0, 40) || "未命名会话";
  return {
    ...store,
    sessions: store.sessions.map((s) =>
      s.id === sessionId ? { ...s, title: nextTitle, updatedAt: new Date().toISOString() } : s,
    ),
  };
};

export const appendSessionMessage = (
  session: AgentSession,
  input: Omit<AgentSessionMessage, "id" | "createdAt"> & { id?: string; createdAt?: string },
): AgentSession => {
  const message: AgentSessionMessage = {
    id: input.id || uid(),
    role: input.role,
    content: (input.content || "").slice(0, 4000),
    createdAt: input.createdAt || new Date().toISOString(),
    kind: input.kind,
    meta: input.meta,
  };
  return {
    ...session,
    updatedAt: message.createdAt,
    messages: [...session.messages, message].slice(-MAX_SESSION_MESSAGES),
  };
};

export const bindTasksToSession = (session: AgentSession, taskIds: number[]): AgentSession => {
  if (!taskIds.length) return session;
  const merged = [...session.taskIds];
  for (const id of taskIds) {
    if (!merged.includes(id)) merged.push(id);
  }
  return {
    ...session,
    taskIds: merged.slice(-MAX_SESSION_TASK_IDS),
    focusTaskId: taskIds[0] ?? session.focusTaskId,
    updatedAt: new Date().toISOString(),
  };
};

export const deriveSessionTitleFromIntent = (intent: string, fallback: string): string => {
  const value = (intent || "").replace(/\s+/g, " ").trim();
  if (!value) return fallback;
  // Prefer first clause
  const clipped = value.split(/[。！？\n]/)[0]?.trim() || value;
  return clipped.slice(0, 18) + (clipped.length > 18 ? "…" : "");
};

/** Build planning context strictly from the active session (never other sessions). */
export const buildSessionContextBlock = (input: {
  session: AgentSession;
  focusPrompt?: string | null;
  focusModelName?: string | null;
  styleKitLabels?: string[];
  brandLabel?: string | null;
}) => {
  const lines: string[] = [];
  lines.push(`会话：${input.session.title}（id=${input.session.id}）`);
  lines.push(
    `会话规模：对话 ${input.session.messages.length} 轮 · 绑定任务 ${input.session.taskIds.length} · 文档 ${input.session.documents.length}`,
  );
  lines.push("规则：只使用本会话上下文；禁止引用其他会话或系统机密；禁止假设其他会话内容。");
  if (input.focusPrompt) lines.push(`本会话焦点作品提示词：${input.focusPrompt.slice(0, 400)}`);
  if (input.focusModelName) lines.push(`焦点模型：${input.focusModelName}`);
  if (input.styleKitLabels?.length) lines.push(`风格包：${input.styleKitLabels.join("、")}`);
  if (input.brandLabel) lines.push(`品牌规范：${input.brandLabel}`);
  if (input.session.lastPlanSummary) lines.push(`上一计划摘要：${input.session.lastPlanSummary.slice(0, 240)}`);
  if (input.session.recentIntents.length) {
    lines.push(`本会话最近意图：${input.session.recentIntents.slice(-4).join(" | ")}`);
  }
  const recentMsgs = input.session.messages.slice(-6);
  if (recentMsgs.length) {
    lines.push("本会话近期对话：");
    for (const msg of recentMsgs) {
      const who = msg.role === "user" ? "用户" : msg.role === "agent" ? "Agent" : "系统";
      lines.push(`- ${who}: ${msg.content.slice(0, 220)}`);
    }
  }
  if (input.session.documents.length) {
    lines.push(
      `本会话文档：${input.session.documents.map((d) => d.name).join("、")}（正文已在 document_text 中，仅本会话）`,
    );
  }
  return `【创作会话上下文 · 仅限当前会话 · 勿串用其他会话】\n${lines.join("\n")}`;
};

export const formatSessionTime = (iso: string): string => {
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return "";
  const diff = Date.now() - ts;
  if (diff < 60_000) return "刚刚";
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
  return new Date(ts).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
};

/** Prefer scoped feed (default true). Stored separately so it is a user preference, not per-session. */
export const SESSION_FEED_ONLY_KEY = "imagine.agent.sessionFeedOnly.v1";

export const loadSessionFeedOnly = (): boolean => {
  try {
    const raw = localStorage.getItem(SESSION_FEED_ONLY_KEY);
    if (raw === null) return true;
    return raw !== "0" && raw !== "false";
  } catch {
    return true;
  }
};

export const saveSessionFeedOnly = (value: boolean) => {
  try {
    localStorage.setItem(SESSION_FEED_ONLY_KEY, value ? "1" : "0");
  } catch {
    // ignore
  }
};

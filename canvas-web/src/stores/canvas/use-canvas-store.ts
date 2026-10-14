import { create } from "zustand";
import { nanoid } from "nanoid";
import type { CanvasBackgroundMode } from "@/lib/canvas-theme";
import type { CanvasAssistantSession, CanvasConnection, CanvasNodeData, ViewportTransform } from "@/types/canvas";
import { callHost } from "@/integration/bridge";
import type { ProjectRecord, ProjectSave, ProjectSummary } from "@/integration/protocol";

export type CanvasProject = {
    id: string;
    nodeCount?: number;
    connectionCount?: number;
    title: string;
    createdAt: string;
    updatedAt: string;
    nodes: CanvasNodeData[];
    connections: CanvasConnection[];
    chatSessions: CanvasAssistantSession[];
    activeChatId: string | null;
    backgroundMode: CanvasBackgroundMode;
    showImageInfo: boolean;
    viewport: ViewportTransform;
};

export type CanvasDeletedProject = {
    id: string;
    deletedAt: string;
};

type CanvasStore = {
    hydrated: boolean;
    projects: CanvasProject[];
    deletedProjects: CanvasDeletedProject[];
    hasMore: boolean;
    saving: boolean;
    error: string;
    createProject: (title?: string) => string;
    importProject: (project: Partial<CanvasProject>) => string;
    openProject: (id: string) => CanvasProject | null;
    loadProject: (id: string) => Promise<CanvasProject>;
    loadMore: () => Promise<void>;
    renameProject: (id: string, title: string) => void;
    deleteProjects: (ids: string[]) => Promise<void>;
    replaceProjects: (projects: CanvasProject[], deletedProjects?: CanvasDeletedProject[]) => void;
    updateProject: (id: string, patch: Partial<CanvasProject>) => void;
};
const revisions = new Map<string, number>();
const loaded = new Set<string>();
const removed = new Set<string>();
const pending = new Map<string, CanvasProject>();
const failed = new Map<string, ProjectSave>();
const errors = new Map<string, string>();
const running = new Map<string, Promise<void>>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
let cursor: ProjectSummary | undefined;
let loadingPage: Promise<void> | null = null;
const initialViewport: ViewportTransform = { x: 0, y: 0, k: 1 };

function emptyProject(id: string, title: string): CanvasProject {
    const now = new Date().toISOString();
    return { id, title, createdAt: now, updatedAt: now, nodes: [], connections: [], chatSessions: [], activeChatId: null, backgroundMode: "lines", showImageInfo: false, viewport: initialViewport };
}
function readProject(record: ProjectRecord): CanvasProject {
    return { ...emptyProject(record.id, record.title), ...record.document, id: record.id, title: record.title, createdAt: record.created_at, updatedAt: record.updated_at } as CanvasProject;
}
function updateStatus() {
    useCanvasStore.setState({ saving: pending.size > 0 || running.size > 0, error: [...errors.values()][0] || "" });
}
function queueSave(project: CanvasProject) {
    if (removed.has(project.id)) return;
    pending.set(project.id, project);
    clearTimeout(timers.get(project.id));
    timers.set(project.id, setTimeout(() => { if (!failed.has(project.id)) void flushProject(project.id).catch(() => undefined); }, 400));
    updateStatus();
}
export async function flushProject(id: string): Promise<void> {
    clearTimeout(timers.get(id));
    timers.delete(id);
    const existing = running.get(id);
    if (existing) return existing;
    const work = async () => {
        while (pending.has(id) || failed.has(id)) {
            const snapshot = pending.get(id);
            const retry = failed.get(id);
            const job = retry || { id, title: snapshot!.title, revision: revisions.get(id) || 0, mutation_id: crypto.randomUUID(), document: snapshot! as unknown as Record<string, unknown> };
            try {
                const result = await callHost("projects.save", job);
                revisions.set(id, result.revision);
                failed.delete(id);
                errors.delete(id);
                // A retry can be an older snapshot than the latest unsaved edit.
                if ((!retry && pending.get(id) === snapshot) || pending.get(id) === job.document) pending.delete(id);
            } catch (error) {
                failed.set(id, job);
                errors.set(id, error instanceof Error ? error.message : "画布保存失败");
                throw error;
            }
        }
    };
    const promise = work().finally(() => { running.delete(id); updateStatus(); });
    running.set(id, promise);
    updateStatus();
    return promise;
}
export async function flushCanvasProjects() {
    await Promise.all([...new Set([...pending.keys(), ...failed.keys(), ...running.keys()])].map(flushProject));
}
window.addEventListener("beforeunload", (event) => {
    if (pending.size || failed.size || running.size) { event.preventDefault(); event.returnValue = ""; }
});
window.addEventListener("visibilitychange", () => { if (document.hidden) void flushCanvasProjects().catch(() => undefined); });

export const useCanvasStore = create<CanvasStore>((set, get) => ({
    hydrated: false, projects: [], deletedProjects: [], hasMore: false, saving: false, error: "",
    createProject(title = "未命名画布") { return get().importProject({ title }); },
    importProject(source) {
        const project = { ...emptyProject(nanoid(), source.title || "导入的画布"), ...source, id: nanoid(), updatedAt: new Date().toISOString() };
        loaded.add(project.id);
        set((state) => ({ projects: [project, ...state.projects] }));
        queueSave(project);
        return project.id;
    },
    openProject: (id) => get().projects.find((project) => project.id === id) || null,
    async loadProject(id) {
        if (loaded.has(id)) return get().openProject(id)!;
        const record = await callHost("projects.get", { id });
        const project = readProject(record);
        revisions.set(id, record.revision);
        loaded.add(id);
        set((state) => ({ projects: [...state.projects.filter((item) => item.id !== id), project] }));
        return project;
    },
    async loadMore() {
        if (loadingPage) return loadingPage;
        loadingPage = (async () => {
            const result = await callHost("projects.list", cursor ? { before_created_at: cursor.created_at, before_id: cursor.id } : {});
            result.items.forEach((item) => { if (!loaded.has(item.id)) revisions.set(item.id, item.revision); });
            cursor = result.items.at(-1) || cursor;
            set((state) => ({ hydrated: true, hasMore: result.has_more, projects: [...state.projects, ...result.items.filter((item) => !state.projects.some((p) => p.id === item.id)).map((item) => ({ ...emptyProject(item.id, item.title), nodeCount: item.node_count, connectionCount: item.connection_count, createdAt: item.created_at, updatedAt: item.updated_at }))] }));
        })().finally(() => { loadingPage = null; });
        return loadingPage;
    },
    renameProject(id, title) {
        void get().loadProject(id).then(() => get().updateProject(id, { title: title.trim().slice(0, 200) || get().openProject(id)!.title })).catch((error) => set({ error: error.message }));
    },
    async deleteProjects(ids) {
        for (const id of ids) {
            await flushProject(id);
            await callHost("projects.delete", { id, revision: revisions.get(id) || 1 });
            removed.add(id);
            loaded.delete(id);
            set((state) => ({ projects: state.projects.filter((item) => item.id !== id) }));
        }
    },
    replaceProjects(projects) { projects.forEach((project) => get().importProject(project)); },
    updateProject(id, patch) {
        if (!loaded.has(id) || removed.has(id)) return;
        const current = get().openProject(id);
        if (!current) return;
        const project = { ...current, ...patch, id, nodeCount: undefined, connectionCount: undefined, updatedAt: new Date().toISOString() };
        set((state) => ({ projects: state.projects.map((item) => item.id === id ? project : item) }));
        queueSave(project);
    },
}));

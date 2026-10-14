import {
  CircleHelp,
  Focus,
  Hand,
  ImagePlus,
  Menu,
  Minus,
  MousePointer2,
  Plus,
  Redo2,
  Settings2,
  Sparkles,
  Trash2,
  Type,
  Undo2,
  WandSparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CanvasStage, type CanvasStageHandle } from "./editor/CanvasStage";
import {
  INITIAL_VIEWPORT,
  MAX_ZOOM,
  MIN_ZOOM,
  initialEditorDocument,
} from "./editor/editorConfig";
import type {
  BoardNode,
  BoardNodePatch,
  BoardTool,
  Viewport,
} from "./editor/types";
import { useEditorHistory } from "./editor/useEditorHistory";

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const createId = (prefix: string) => `${prefix}-${crypto.randomUUID()}`;

const starterPrompt =
  "一座隐藏在雾气森林中的现代玻璃屋，室内透出暖光，电影感，安静神秘，高级建筑摄影";

export default function App() {
  const canvasRef = useRef<CanvasStageHandle>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const generationTimerRef = useRef<number | null>(null);
  const { document, commit, undo, redo, canUndo, canRedo } =
    useEditorHistory(initialEditorDocument);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tool, setTool] = useState<BoardTool>("select");
  const [viewport, setViewport] = useState<Viewport>(INITIAL_VIEWPORT);
  const [spacePressed, setSpacePressed] = useState(false);
  const [prompt, setPrompt] = useState(starterPrompt);
  const [model, setModel] = useState("GPT Image");
  const [ratio, setRatio] = useState("1:1");
  const [count, setCount] = useState(4);
  const [isGenerating, setIsGenerating] = useState(false);
  const [notice, setNotice] = useState(
    "输入提示词后点击生成，体验节点式创作流程",
  );

  const selectedNode = useMemo(
    () => document.nodes.find((node) => node.id === selectedId) ?? null,
    [document.nodes, selectedId],
  );

  const updateNode = (nodeId: string, patch: BoardNodePatch) => {
    commit((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === nodeId ? ({ ...node, ...patch } as BoardNode) : node,
      ),
    }));
  };

  const selectNode = (nodeId: string | null) => {
    setSelectedId(nodeId);
    if (!nodeId) return;
    const node = document.nodes.find((item) => item.id === nodeId);
    if (node?.type === "prompt" || node?.type === "image") {
      setPrompt(node.prompt);
    }
  };

  const removeSelected = () => {
    if (!selectedId) return;
    commit((current) => ({
      nodes: current.nodes.filter((node) => node.id !== selectedId),
      connectors: current.connectors.filter(
        (connector) =>
          connector.fromId !== selectedId && connector.toId !== selectedId,
      ),
    }));
    setSelectedId(null);
    setNotice("节点已从画布移除");
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isEditing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT";
      if (event.code === "Space" && !isEditing) {
        event.preventDefault();
        setSpacePressed(true);
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
        return;
      }
      if (isEditing) return;
      if (event.key.toLowerCase() === "v") setTool("select");
      if (event.key.toLowerCase() === "h") setTool("hand");
      if (
        (event.key === "Delete" || event.key === "Backspace") &&
        selectedId
      ) {
        event.preventDefault();
        removeSelected();
      }
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code === "Space") setSpacePressed(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  });

  useEffect(
    () => () => {
      if (generationTimerRef.current) {
        window.clearTimeout(generationTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const generateWorkflow = () => {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt || isGenerating) return;

    const centerX =
      (window.innerWidth * 0.5 - viewport.x) / viewport.scale;
    const centerY =
      ((window.innerHeight - 64) * 0.43 - viewport.y) / viewport.scale;
    const promptId = createId("prompt");
    const generatorId = createId("generator");
    const promptNode: BoardNode = {
      id: promptId,
      type: "prompt",
      x: centerX - 480,
      y: centerY - 95,
      width: 330,
      height: 190,
      prompt: cleanPrompt,
    };
    const generatorNode: BoardNode = {
      id: generatorId,
      type: "generator",
      x: centerX - 30,
      y: centerY - 95,
      width: 290,
      height: 190,
      model,
      ratio,
      count,
      status: "generating",
    };

    commit((current) => ({
      nodes: [...current.nodes, promptNode, generatorNode],
      connectors: [
        ...current.connectors,
        {
          id: createId("line"),
          fromId: promptId,
          toId: generatorId,
        },
      ],
    }));
    setSelectedId(generatorId);
    setIsGenerating(true);
    setNotice("正在把生成任务放到画布上…");

    generationTimerRef.current = window.setTimeout(() => {
      const resultNodes: BoardNode[] = Array.from(
        { length: count },
        (_, index) => ({
          id: createId("image"),
          type: "image",
          x: centerX + 390 + (index % 2) * 285,
          y: centerY - 255 + Math.floor(index / 2) * 285,
          width: 235,
          height: 235,
          prompt: cleanPrompt,
          variant: index,
        }),
      );
      commit((current) => ({
        nodes: [
          ...current.nodes.map((node) =>
            node.id === generatorId && node.type === "generator"
              ? { ...node, status: "complete" as const }
              : node,
          ),
          ...resultNodes,
        ],
        connectors: [
          ...current.connectors,
          ...resultNodes.map((node) => ({
            id: createId("line"),
            fromId: generatorId,
            toId: node.id,
          })),
        ],
      }));
      setSelectedId(resultNodes[0]?.id ?? generatorId);
      setIsGenerating(false);
      setNotice("已生成一组可继续拖拽编排的结果");
    }, 900);
  };

  const changeZoom = (factor: number) => {
    const center = {
      x: window.innerWidth / 2,
      y: (window.innerHeight - 64) / 2,
    };
    const scale = clamp(viewport.scale * factor, MIN_ZOOM, MAX_ZOOM);
    const worldX = (center.x - viewport.x) / viewport.scale;
    const worldY = (center.y - viewport.y) / viewport.scale;
    setViewport({
      scale,
      x: center.x - worldX * scale,
      y: center.y - worldY * scale,
    });
  };

  return (
    <main className="studio">
      <header className="studio-header">
        <div className="header-left">
          <button className="plain-icon" type="button" aria-label="菜单">
            <Menu size={20} />
          </button>
          <span className="logo">
            <WandSparkles size={17} />
          </span>
          <div className="board-title">
            <strong>视觉概念探索</strong>
            <span>自动保存</span>
          </div>
        </div>

        <div className="header-center">
          <button
            className="plain-icon"
            type="button"
            aria-label="撤销"
            title="撤销（⌘Z）"
            disabled={!canUndo}
            onClick={undo}
          >
            <Undo2 size={17} />
          </button>
          <button
            className="plain-icon"
            type="button"
            aria-label="重做"
            title="重做（⇧⌘Z）"
            disabled={!canRedo}
            onClick={redo}
          >
            <Redo2 size={17} />
          </button>
        </div>

        <div className="header-right">
          <button className="plain-icon" type="button" aria-label="设置">
            <Settings2 size={17} />
          </button>
          <button className="plain-icon" type="button" aria-label="帮助">
            <CircleHelp size={17} />
          </button>
          <span className="version">EXPERIENCE</span>
          <span className="avatar">A</span>
        </div>
      </header>

      <section className="canvas-shell">
        <CanvasStage
          ref={canvasRef}
          document={document}
          selectedId={selectedId}
          tool={tool}
          viewport={viewport}
          spacePressed={spacePressed}
          onViewportChange={setViewport}
          onSelect={selectNode}
          onNodeChange={updateNode}
        />

        <div className="zoom-dock">
          <button
            type="button"
            title="缩小"
            aria-label="缩小"
            onClick={() => changeZoom(1 / 1.15)}
          >
            <Minus size={15} />
          </button>
          <button
            className="zoom-number"
            type="button"
            onClick={() => setViewport({ ...viewport, scale: 1 })}
          >
            {Math.round(viewport.scale * 100)}%
          </button>
          <button
            type="button"
            title="适应全部"
            aria-label="适应全部"
            onClick={() => canvasRef.current?.fitToContent()}
          >
            <Focus size={15} />
          </button>
          <button
            type="button"
            title="放大"
            aria-label="放大"
            onClick={() => changeZoom(1.15)}
          >
            <Plus size={15} />
          </button>
        </div>

        <div className="tool-dock">
          <button
            className={tool === "select" ? "active" : ""}
            type="button"
            title="选择（V）"
            onClick={() => setTool("select")}
          >
            <MousePointer2 size={18} />
          </button>
          <button
            className={tool === "hand" ? "active" : ""}
            type="button"
            title="移动画布（H / 空格）"
            onClick={() => setTool("hand")}
          >
            <Hand size={18} />
          </button>
          <span />
          <button
            type="button"
            title="添加提示词"
            onClick={() => promptRef.current?.focus()}
          >
            <Type size={18} />
          </button>
          <button type="button" title="添加图片节点">
            <ImagePlus size={18} />
          </button>
          {selectedNode ? (
            <>
              <span />
              <button
                className="danger"
                type="button"
                title="删除选中节点"
                onClick={removeSelected}
              >
                <Trash2 size={18} />
              </button>
            </>
          ) : null}
        </div>

        <div className="prompt-composer">
          <div className="composer-main">
            <span className="composer-spark">
              <Sparkles size={16} />
            </span>
            <textarea
              ref={promptRef}
              rows={2}
              value={prompt}
              placeholder="描述你想生成的画面…"
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                  event.preventDefault();
                  generateWorkflow();
                }
              }}
            />
            <button
              className="generate-button"
              type="button"
              disabled={!prompt.trim() || isGenerating}
              onClick={generateWorkflow}
            >
              {isGenerating ? "生成中…" : "生成到画布"}
              {!isGenerating ? <WandSparkles size={15} /> : null}
            </button>
          </div>
          <div className="composer-options">
            <select
              aria-label="生成模型"
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              <option>GPT Image</option>
              <option>Flux Pro</option>
              <option>Seedream</option>
            </select>
            <select
              aria-label="图片比例"
              value={ratio}
              onChange={(event) => setRatio(event.target.value)}
            >
              <option>1:1</option>
              <option>4:3</option>
              <option>16:9</option>
              <option>3:4</option>
            </select>
            <select
              aria-label="生成数量"
              value={count}
              onChange={(event) => setCount(Number(event.target.value))}
            >
              <option value={1}>1 张</option>
              <option value={2}>2 张</option>
              <option value={4}>4 张</option>
            </select>
            <span className="composer-tip">⌘ Enter 快速生成</span>
          </div>
        </div>

        {notice ? <div className="toast">{notice}</div> : null}
      </section>
    </main>
  );
}

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import Konva from "konva";
import {
  Arrow,
  Circle,
  Group,
  Layer,
  Line,
  Rect,
  Stage,
  Text,
} from "react-konva";
import { GRID_SIZE, MAX_ZOOM, MIN_ZOOM } from "./editorConfig";
import type {
  BoardNode,
  BoardNodePatch,
  BoardTool,
  EditorDocument,
  ImageNode,
  Viewport,
} from "./types";

export type CanvasStageHandle = {
  fitToContent: () => void;
};

type CanvasStageProps = {
  document: EditorDocument;
  selectedId: string | null;
  tool: BoardTool;
  viewport: Viewport;
  spacePressed: boolean;
  onViewportChange: (viewport: Viewport) => void;
  onSelect: (nodeId: string | null) => void;
  onNodeChange: (nodeId: string, patch: BoardNodePatch) => void;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

function Port({ x, y }: { x: number; y: number }) {
  return (
    <Circle
      x={x}
      y={y}
      radius={5}
      fill="#181818"
      stroke="#a7abb2"
      strokeWidth={2}
    />
  );
}

function PromptCard({
  node,
  selected,
}: {
  node: Extract<BoardNode, { type: "prompt" }>;
  selected: boolean;
}) {
  return (
    <>
      <Rect
        width={node.width}
        height={node.height}
        cornerRadius={18}
        fill="#242322"
        stroke={selected ? "#7b8cff" : "#474747"}
        strokeWidth={selected ? 2 : 1}
        shadowColor="#000"
        shadowBlur={selected ? 24 : 12}
        shadowOpacity={0.25}
        shadowOffsetY={8}
      />
      <Text
        x={20}
        y={18}
        text="提示词"
        fill="#95928f"
        fontSize={12}
        fontStyle="600"
      />
      <Text
        x={20}
        y={48}
        width={node.width - 40}
        height={node.height - 68}
        text={node.prompt}
        fill="#f0eeeb"
        fontSize={16}
        fontFamily="Inter, system-ui, sans-serif"
        lineHeight={1.55}
        wrap="word"
        ellipsis
      />
      <Port x={node.width} y={node.height / 2} />
    </>
  );
}

function GeneratorCard({
  node,
  selected,
}: {
  node: Extract<BoardNode, { type: "generator" }>;
  selected: boolean;
}) {
  return (
    <>
      <Rect
        width={node.width}
        height={node.height}
        cornerRadius={18}
        fill="#242322"
        stroke={selected ? "#7b8cff" : "#474747"}
        strokeWidth={selected ? 2 : 1}
        shadowColor="#000"
        shadowBlur={selected ? 24 : 12}
        shadowOpacity={0.25}
        shadowOffsetY={8}
      />
      <Text
        x={18}
        y={17}
        text="生成配置"
        fill="#f2f0ed"
        fontSize={14}
        fontStyle="600"
      />
      <Rect
        x={18}
        y={48}
        width={node.width - 36}
        height={42}
        cornerRadius={10}
        fill="#1b1a1a"
        stroke="#3a3939"
        strokeWidth={1}
      />
      <Text
        x={31}
        y={62}
        text={node.model}
        fill="#dedbd7"
        fontSize={13}
      />
      <Text
        x={node.width - 104}
        y={62}
        text={`${node.ratio}  ·  ${node.count} 张`}
        fill="#8e8b88"
        fontSize={12}
      />
      <Rect
        x={18}
        y={105}
        width={node.width - 36}
        height={48}
        cornerRadius={11}
        fill={node.status === "generating" ? "#474a55" : "#eeece9"}
      />
      <Text
        x={18}
        y={121}
        width={node.width - 36}
        align="center"
        text={node.status === "generating" ? "正在生成…" : "✦  生成图片"}
        fill={node.status === "generating" ? "#c6c8d0" : "#242322"}
        fontSize={13}
        fontStyle="600"
      />
      <Port x={0} y={node.height / 2} />
      <Port x={node.width} y={node.height / 2} />
    </>
  );
}

const palettes = [
  ["#99d4ff", "#f4b47c", "#343a74", "#f6e7ca"],
  ["#ff8577", "#501f71", "#15132f", "#ffcc87"],
  ["#d7f5ff", "#6ab7d3", "#d18e52", "#f2dfb5"],
  ["#8e9cff", "#151c45", "#db7e92", "#f1c5b4"],
] as const;

function Artwork({ node }: { node: ImageNode }) {
  const palette = palettes[node.variant % palettes.length];
  const size = node.width;
  return (
    <>
      <Rect
        width={node.width}
        height={node.height}
        cornerRadius={16}
        fillLinearGradientStartPoint={{ x: 0, y: 0 }}
        fillLinearGradientEndPoint={{ x: size, y: size }}
        fillLinearGradientColorStops={[
          0,
          palette[0],
          0.48,
          palette[1],
          1,
          palette[2],
        ]}
      />
      <Circle
        x={size * (node.variant % 2 ? 0.72 : 0.28)}
        y={size * 0.26}
        radius={size * 0.13}
        fill={palette[3]}
        opacity={0.95}
        shadowColor={palette[3]}
        shadowBlur={24}
        shadowOpacity={0.5}
      />
      <Rect
        x={size * 0.15}
        y={size * 0.42}
        width={size * 0.7}
        height={size * 0.49}
        cornerRadius={[70, 70, 10, 10]}
        fill="#141625"
        opacity={0.88}
      />
      <Rect
        x={size * 0.27}
        y={size * 0.53}
        width={size * 0.46}
        height={size * 0.38}
        cornerRadius={[60, 60, 4, 4]}
        fill={palette[0]}
        opacity={0.72}
      />
      <Line
        points={[
          size * 0.05,
          size * 0.8,
          size * 0.3,
          size * 0.73,
          size * 0.56,
          size * 0.83,
          size * 0.95,
          size * 0.7,
        ]}
        stroke={palette[3]}
        strokeWidth={2}
        opacity={0.6}
        tension={0.5}
      />
    </>
  );
}

function ImageCard({
  node,
  selected,
}: {
  node: ImageNode;
  selected: boolean;
}) {
  return (
    <>
      <Artwork node={node} />
      <Rect
        width={node.width}
        height={node.height}
        cornerRadius={16}
        stroke={selected ? "#6f83ff" : "#3f4148"}
        strokeWidth={selected ? 3 : 1}
        shadowColor="#000"
        shadowBlur={selected ? 26 : 13}
        shadowOpacity={0.35}
        shadowOffsetY={8}
      />
      <Rect
        x={node.width - 42}
        y={12}
        width={29}
        height={27}
        cornerRadius={8}
        fill="rgba(21,21,24,.7)"
      />
      <Text
        x={node.width - 42}
        y={20}
        width={29}
        align="center"
        text={String(node.variant + 1)}
        fill="#dfe3ff"
        fontSize={11}
        fontStyle="600"
      />
      <Port x={0} y={node.height / 2} />
      <Port x={node.width} y={node.height / 2} />
    </>
  );
}

export const CanvasStage = forwardRef<CanvasStageHandle, CanvasStageProps>(
  (
    {
      document,
      selectedId,
      tool,
      viewport,
      spacePressed,
      onViewportChange,
      onSelect,
      onNodeChange,
    },
    forwardedRef,
  ) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const stageRef = useRef<Konva.Stage>(null);
    const panStartRef = useRef<{
      pointerX: number;
      pointerY: number;
      viewportX: number;
      viewportY: number;
    } | null>(null);
    const [containerSize, setContainerSize] = useState({
      width: 1000,
      height: 700,
    });
    const isPanning = tool === "hand" || spacePressed;

    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;
      const observer = new ResizeObserver(([entry]) => {
        setContainerSize({
          width: Math.max(320, entry.contentRect.width),
          height: Math.max(320, entry.contentRect.height),
        });
      });
      observer.observe(container);
      return () => observer.disconnect();
    }, []);

    useImperativeHandle(
      forwardedRef,
      () => ({
        fitToContent: () => {
          if (document.nodes.length === 0) return;
          const minX = Math.min(...document.nodes.map((node) => node.x));
          const minY = Math.min(...document.nodes.map((node) => node.y));
          const maxX = Math.max(
            ...document.nodes.map((node) => node.x + node.width),
          );
          const maxY = Math.max(
            ...document.nodes.map((node) => node.y + node.height),
          );
          const scale = clamp(
            Math.min(
              (containerSize.width - 150) / (maxX - minX),
              (containerSize.height - 150) / (maxY - minY),
            ),
            MIN_ZOOM,
            1.05,
          );
          onViewportChange({
            x: (containerSize.width - (maxX - minX) * scale) / 2 - minX * scale,
            y: (containerSize.height - (maxY - minY) * scale) / 2 - minY * scale,
            scale,
          });
        },
      }),
      [containerSize, document.nodes, onViewportChange],
    );

    const screenToWorld = (point: { x: number; y: number }) => ({
      x: (point.x - viewport.x) / viewport.scale,
      y: (point.y - viewport.y) / viewport.scale,
    });

    const handleWheel = (event: Konva.KonvaEventObject<WheelEvent>) => {
      event.evt.preventDefault();
      const pointer = stageRef.current?.getPointerPosition();
      if (!pointer) return;
      const world = screenToWorld(pointer);
      const scale = clamp(
        viewport.scale * (event.evt.deltaY > 0 ? 1 / 1.08 : 1.08),
        MIN_ZOOM,
        MAX_ZOOM,
      );
      onViewportChange({
        scale,
        x: pointer.x - world.x * scale,
        y: pointer.y - world.y * scale,
      });
    };

    const beginPan = (
      event: Konva.KonvaEventObject<MouseEvent | TouchEvent>,
    ) => {
      const pointer = stageRef.current?.getPointerPosition();
      if (!pointer) return;
      const button = "button" in event.evt ? event.evt.button : 0;
      if (isPanning || button === 1) {
        panStartRef.current = {
          pointerX: pointer.x,
          pointerY: pointer.y,
          viewportX: viewport.x,
          viewportY: viewport.y,
        };
      } else if (event.target === stageRef.current) {
        onSelect(null);
      }
    };

    const continuePan = () => {
      const pointer = stageRef.current?.getPointerPosition();
      const start = panStartRef.current;
      if (!pointer || !start) return;
      onViewportChange({
        ...viewport,
        x: start.viewportX + pointer.x - start.pointerX,
        y: start.viewportY + pointer.y - start.pointerY,
      });
    };

    const gridScale = GRID_SIZE * viewport.scale;

    return (
      <div
        ref={containerRef}
        className={`infinite-canvas${isPanning ? " is-panning" : ""}`}
        style={{
          backgroundSize: `${gridScale}px ${gridScale}px`,
          backgroundPosition: `${viewport.x}px ${viewport.y}px`,
        }}
      >
        <Stage
          ref={stageRef}
          width={containerSize.width}
          height={containerSize.height}
          onWheel={handleWheel}
          onMouseDown={beginPan}
          onMouseMove={continuePan}
          onMouseUp={() => {
            panStartRef.current = null;
          }}
          onMouseLeave={() => {
            panStartRef.current = null;
          }}
          onTouchStart={beginPan}
          onTouchMove={continuePan}
          onTouchEnd={() => {
            panStartRef.current = null;
          }}
        >
          <Layer
            x={viewport.x}
            y={viewport.y}
            scaleX={viewport.scale}
            scaleY={viewport.scale}
          >
            {document.connectors.map((connector) => {
              const from = document.nodes.find(
                (node) => node.id === connector.fromId,
              );
              const to = document.nodes.find(
                (node) => node.id === connector.toId,
              );
              if (!from || !to) return null;
              const startX = from.x + from.width;
              const startY = from.y + from.height / 2;
              const endX = to.x;
              const endY = to.y + to.height / 2;
              const bend = Math.max(70, Math.abs(endX - startX) * 0.45);
              return (
                <Arrow
                  key={connector.id}
                  points={[
                    startX,
                    startY,
                    startX + bend,
                    startY,
                    endX - bend,
                    endY,
                    endX,
                    endY,
                  ]}
                  bezier
                  stroke="#a4a5a8"
                  fill="#a4a5a8"
                  strokeWidth={2}
                  pointerLength={6}
                  pointerWidth={6}
                  opacity={0.8}
                />
              );
            })}
            {document.nodes.map((node) => (
              <Group
                key={node.id}
                x={node.x}
                y={node.y}
                width={node.width}
                height={node.height}
                draggable={tool === "select" && !spacePressed}
                onClick={(event) => {
                  event.cancelBubble = true;
                  onSelect(node.id);
                }}
                onTap={(event) => {
                  event.cancelBubble = true;
                  onSelect(node.id);
                }}
                onDragEnd={(event) =>
                  onNodeChange(node.id, {
                    x: event.target.x(),
                    y: event.target.y(),
                  })
                }
              >
                {node.type === "prompt" ? (
                  <PromptCard node={node} selected={selectedId === node.id} />
                ) : node.type === "generator" ? (
                  <GeneratorCard node={node} selected={selectedId === node.id} />
                ) : (
                  <ImageCard node={node} selected={selectedId === node.id} />
                )}
              </Group>
            ))}
          </Layer>
        </Stage>
      </div>
    );
  },
);

CanvasStage.displayName = "CanvasStage";

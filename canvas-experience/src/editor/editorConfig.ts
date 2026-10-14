import type { EditorDocument, Viewport } from "./types";

export const HISTORY_LIMIT = 80;
export const MIN_ZOOM = 0.18;
export const MAX_ZOOM = 2.2;
export const GRID_SIZE = 32;

export const INITIAL_VIEWPORT: Viewport = {
  x: 92,
  y: 82,
  scale: 0.76,
};

const starterPrompt =
  "一座漂浮在云海上的未来美术馆，巨大的弧形玻璃结构，黄昏暖光，电影感构图，细腻材质，建筑摄影";

export const initialEditorDocument: EditorDocument = {
  nodes: [
    {
      id: "prompt-1",
      type: "prompt",
      x: 40,
      y: 260,
      width: 330,
      height: 190,
      prompt: starterPrompt,
    },
    {
      id: "generator-1",
      type: "generator",
      x: 485,
      y: 260,
      width: 290,
      height: 190,
      model: "GPT Image",
      ratio: "1:1",
      count: 4,
      status: "complete",
    },
    {
      id: "image-1",
      type: "image",
      x: 910,
      y: -20,
      width: 235,
      height: 235,
      prompt: starterPrompt,
      variant: 0,
    },
    {
      id: "image-2",
      type: "image",
      x: 910,
      y: 245,
      width: 235,
      height: 235,
      prompt: starterPrompt,
      variant: 1,
    },
    {
      id: "image-3",
      type: "image",
      x: 910,
      y: 510,
      width: 235,
      height: 235,
      prompt: starterPrompt,
      variant: 2,
    },
    {
      id: "image-4",
      type: "image",
      x: 1220,
      y: 245,
      width: 235,
      height: 235,
      prompt: starterPrompt,
      variant: 3,
    },
  ],
  connectors: [
    { id: "line-prompt-generator", fromId: "prompt-1", toId: "generator-1" },
    { id: "line-generator-image-1", fromId: "generator-1", toId: "image-1" },
    { id: "line-generator-image-2", fromId: "generator-1", toId: "image-2" },
    { id: "line-generator-image-3", fromId: "generator-1", toId: "image-3" },
    { id: "line-generator-image-4", fromId: "generator-1", toId: "image-4" },
  ],
};

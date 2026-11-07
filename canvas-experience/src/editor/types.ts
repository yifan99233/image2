export type BoardTool = "select" | "hand";

type NodeBase = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PromptNode = NodeBase & {
  type: "prompt";
  prompt: string;
};

export type GeneratorNode = NodeBase & {
  type: "generator";
  model: string;
  ratio: string;
  count: number;
  status: "ready" | "generating" | "complete";
};

export type ImageNode = NodeBase & {
  type: "image";
  prompt: string;
  variant: number;
};

export type BoardNode = PromptNode | GeneratorNode | ImageNode;

export type BoardNodePatch = Partial<{
  x: number;
  y: number;
  width: number;
  height: number;
  prompt: string;
  model: string;
  ratio: string;
  count: number;
  status: GeneratorNode["status"];
}>;

export type BoardConnector = {
  id: string;
  fromId: string;
  toId: string;
};

export type EditorDocument = {
  nodes: BoardNode[];
  connectors: BoardConnector[];
};

export type Viewport = {
  x: number;
  y: number;
  scale: number;
};

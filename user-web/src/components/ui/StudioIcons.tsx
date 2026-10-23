import { createLucideIcon, type IconNode } from "lucide-react";

// A shared 24 px grid keeps feature icons consistent across navigation and cards.
const icon = (name: string, nodes: IconNode) => createLucideIcon(`Studio${name}`, nodes);
const wash = { fill: "currentColor", fillOpacity: "0.12" };

export const Home = icon("Home", [
  ["path", { d: "M3 10 12 3l9 7v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z", ...wash, key: "house" }],
  ["path", { d: "M9 21v-8h6v8", key: "door" }],
]);
export const Wand2 = icon("ImageEdit", [
  ["rect", { x: "3", y: "5", width: "16", height: "16", rx: "4", ...wash, key: "frame" }],
  ["path", { d: "m3 16 5-5 6 7M15 3v6m-3-3h6m3 4v4m-2-2h4", key: "edit" }],
]);
export const Image = icon("TextImage", [
  ["rect", { x: "3", y: "3", width: "18", height: "18", rx: "4", ...wash, key: "frame" }],
  ["path", { d: "M7 7h6m-3 0v5m-4 9 5-6 4 4 3-3 3 3", key: "text-landscape" }],
]);
export const Images = icon("BatchImage", [
  ["path", { d: "M17 3H5a2 2 0 0 0-2 2v12", key: "back" }],
  ["rect", { x: "7", y: "7", width: "14", height: "14", rx: "3", ...wash, key: "front" }],
  ["path", { d: "m7 17 4-4 5 5 2-2 3 3", key: "landscape" }],
  ["circle", { cx: "17", cy: "11", r: "0.8", fill: "currentColor", stroke: "none", key: "sun" }],
]);
export const Layers3 = icon("BatchEdit", [
  ["path", { d: "m3 8 9-5 9 5-9 5Z", ...wash, key: "layer" }],
  ["path", { d: "m3 13 9 5 9-5M3 18l9 5 9-5", key: "stack" }],
]);
export const Frame = icon("Canvas", [
  ["rect", { x: "5", y: "5", width: "14", height: "14", rx: "2", ...wash, key: "canvas" }],
  ["path", { d: "M3 8V3h5m8 0h5v5m0 8v5h-5M8 21H3v-5", key: "corners" }],
]);
export const Sparkles = icon("Explore", [
  ["path", { d: "m10 3 2.5 6.5L19 12l-6.5 2.5L10 21l-2.5-6.5L1 12l6.5-2.5Z", ...wash, key: "star" }],
  ["path", { d: "M20 2v5m-2.5-2.5h5M20 18v4m-2-2h4", key: "sparkles" }],
]);
export const Library = icon("Materials", [
  ["path", { d: "M3 8V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z", ...wash, key: "folder" }],
  ["path", { d: "M8 12h8m-8 4h5", key: "contents" }],
]);
export const GalleryHorizontalEnd = icon("Works", [
  ["rect", { x: "3", y: "7", width: "18", height: "14", rx: "3", ...wash, key: "frame" }],
  ["path", { d: "M7 3h10M5 5h14m-11 16 5-6 4 4 3-3 3 3", key: "gallery" }],
  ["circle", { cx: "8", cy: "12", r: "1", fill: "currentColor", stroke: "none", key: "sun" }],
]);
export const Clapperboard = icon("TextVideo", [
  ["rect", { x: "3", y: "4", width: "18", height: "17", rx: "3", ...wash, key: "frame" }],
  ["path", { d: "M3 9h18M9 4 6 9m9-5-3 5m9-5-3 5m-8 3 5 3-5 3Z", key: "video" }],
]);
export const Film = icon("ImageVideo", [
  ["rect", { x: "3", y: "3", width: "18", height: "18", rx: "4", ...wash, key: "frame" }],
  ["path", { d: "m10 8 6 4-6 4ZM3 8h3M3 16h3m12-8h3m-3 8h3", key: "film" }],
]);
export const ContactRound = icon("Audience", [
  ["rect", { x: "3", y: "4", width: "18", height: "17", rx: "4", ...wash, key: "card" }],
  ["circle", { cx: "10", cy: "10", r: "2.5", key: "person" }],
  ["path", { d: "M6 18v-1a4 4 0 0 1 8 0v1m2-9h2m-2 4h2M8 2v4", key: "details" }],
]);

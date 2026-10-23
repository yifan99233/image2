import { GalleryHorizontalEnd, Frame, Home, Image, Images, Layers3, Library, ContactRound, Clapperboard, Film, Sparkles, Wand2 } from "@/components/ui/StudioIcons";
import type { NavigationGroup } from "@/types/navigation";

export const navigationGroups: NavigationGroup[] = [
  {
    label: "创作",
    items: [
      { label: "首页", path: "/dashboard", icon: Home, moduleKey: "dashboard" },
    ],
  },
  {
    label: "图片创意",
    items: [
      { label: "创作广场", path: "/gallery", icon: Sparkles, moduleKey: "gallery" },
      { label: "画布", path: "/create/canvas", icon: Frame, moduleKey: "text_to_image" },
      { label: "图生图", path: "/create/edit", icon: Wand2, moduleKey: "image_edit" },
      { label: "文生图", path: "/create/text-to-image", icon: Image, moduleKey: "text_to_image" },
      { label: "批量生图", path: "/create/batch-generate", icon: Images, moduleKey: "batch_generate" },
      { label: "批量改图", path: "/create/batch-edit", icon: Layers3, moduleKey: "batch_edit" },
      { label: "素材库", path: "/materials", icon: Library, moduleKey: "works" },
      { label: "我的作品", path: "/works", icon: GalleryHorizontalEnd, moduleKey: "works" },
    ],
  },
  {
    label: "视频创意",
    items: [
      { label: "文生视频", path: "/create/text-to-video", icon: Clapperboard, moduleKey: "text_to_video" },
      { label: "图生视频", path: "/create/image-to-video", icon: Film, moduleKey: "image_to_video" },
    ],
  },
  {
    label: "AI高效精准获客",
    moduleKey: "leads",
    items: [
      { label: "AI高效精准获客", path: "/leads", icon: ContactRound },
    ],
  },
];

type UtilityLink = {
  label: string;
  path: string;
};

export const utilityLinks: UtilityLink[] = [
  // Hidden in the current version:
  // { label: "API接入", path: "/developer/api" },
  // { label: "OpenClaw接入", path: "/developer/openclaw" },
  // { label: "版权服务", path: "/license" },
] as const;

export const topbarActionLinks = [
  { label: "用户反馈", path: "/feedback", tone: "neutral", moduleKey: "feedback" },
  { label: "联系客服", path: "/support", tone: "neutral", moduleKey: "support" },
  { label: "签到 +积分", path: "/rewards/signin", tone: "success", moduleKey: "signin" },
  { label: "邀请 赚积分", path: "/rewards/invite", tone: "pink", moduleKey: "invite" },
] as const;

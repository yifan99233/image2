import { request } from "@/services/http";
import type { SiteConfig } from "@/types/api";

export const defaultSiteConfig: SiteConfig = {
  id: 1,
  site_key: "main",
  site_name: "艺源",
  site_icon_url: "/image2ai-icon.svg",
  frontend_url: "",
  admin_url: "",
  is_default: true,
  is_enabled: true,
  enabled_modules: [
    "dashboard",
    "gallery",
    "image_edit",
    "text_to_image",
    "text_to_video",
    "image_to_video",
    "batch_generate",
    "batch_edit",
    "works",
    "leads",
    "opencode",
    "feedback",
    "support",
    "signin",
    "invite",
    "recharge",
  ],
  support_qq: "1223362085",
  support_wechat: "YiTiao1024L",
  support_wechat_qrcode_url: "/wechat-qrcode.png",
  support_email: "support@example.com",
  homepage_case_carousels: [
    [
      { title: "电商套图", subtitle: "主图、场景图、详情页素材统一生成", image_url: "", file_url: "", link_url: "", tone: "blue" },
      { title: "产品效果图", subtitle: "上传商品图后快速延展应用场景", image_url: "", file_url: "", link_url: "", tone: "orange" },
    ],
    [
      { title: "图片二次优化", subtitle: "改背景、换氛围、补细节", image_url: "", file_url: "", link_url: "", tone: "cyan" },
      { title: "案例展示", subtitle: "生成前后效果直接对比", image_url: "", file_url: "", link_url: "", tone: "green" },
    ],
  ],
  homepage_batch_banners: [],
  lead_case_materials: [
    { title: "家具", subtitle: "家居门店获客案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "blue" },
    { title: "大健康", subtitle: "养生门店转化案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "green" },
    { title: "珠宝", subtitle: "高客单私域案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "orange" },
    { title: "考公", subtitle: "课程线索转化案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "cyan" },
  ],
  opencode_install_video: {
    title: "从需求到交付的自动化流程",
    subtitle: "演示 Codex定制版如何读取需求、修改文件、运行验证并输出结果。",
    file_url: "",
    cover_url: "",
    link_url: "",
    tags: ["写代码", "做文件", "查资料"],
    tone: "blue",
  },
  system_announcement: {
    is_enabled: false,
    title: "",
    content: "",
    image_url: "",
  },
  updated_at: null,
};

export const siteService = {
  getConfig: () => request<SiteConfig>("/site/config", { skipAuth: true }),
};

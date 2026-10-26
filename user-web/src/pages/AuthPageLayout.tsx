import { type PropsWithChildren, useEffect, useState } from "react";
import { ArrowUpRight, ImagePlus, Layers, Type, Video } from "lucide-react";
import { Link } from "react-router-dom";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";

type AuthPageLayoutProps = PropsWithChildren;

const creationFeatures = [
  { title: "文生图", detail: "描述想法，生成图片", icon: Type },
  { title: "图生图", detail: "上传图片，换背景、改风格", icon: ImagePlus },
  { title: "批量创作", detail: "批量生图、改图，减少重复操作", icon: Layers },
  { title: "视频生成", detail: "用文字或图片，生成视频", icon: Video },
];

export const AuthPageLayout = ({ children }: AuthPageLayoutProps) => {
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  return (
    <main className="auth-page auth-page--atelier">
      <header className="atelier-nav">
        <Link className="atelier-brand" to="/login" aria-label={`${siteConfig.site_name}登录页`}>
          <img src={siteConfig.site_icon_url || "/image2ai-icon.svg"} alt="" />
          <span>{siteConfig.site_name}</span>
        </Link>
        <span className="atelier-nav__note">为灵感，留一处空间。</span>
      </header>

      <section className="atelier-layout" aria-label="创作工作台登录">
        <div className="atelier-story">
          <div className="atelier-story__copy">
            <p className="atelier-eyebrow"><span /> AI 图片与视频创作工作台</p>
            <h1>让想法成图，<br /><em>让画面动起来。</em></h1>
            <p className="atelier-summary">从商品图、创意配图到视频素材，<br />在一个工作台里，完成你的视觉创作。</p>
          </div>
          <div className="atelier-art" aria-hidden="true">
            <svg viewBox="0 0 600 370" fill="none">
              <defs>
                <linearGradient id="atelier-arch" x1="205" y1="80" x2="400" y2="335" gradientUnits="userSpaceOnUse"><stop stopColor="#e9e4fb" /><stop offset="1" stopColor="#9295c0" /></linearGradient>
                <linearGradient id="atelier-window" x1="280" y1="120" x2="330" y2="310" gradientUnits="userSpaceOnUse"><stop stopColor="#829b9b" /><stop offset="1" stopColor="#d5dfd0" /></linearGradient>
                <linearGradient id="atelier-floor" x1="100" y1="285" x2="500" y2="370" gradientUnits="userSpaceOnUse"><stop stopColor="#aaaac4" /><stop offset="1" stopColor="#555d7c" /></linearGradient>
                <radialGradient id="atelier-orb" cx=".3" cy=".25" r=".8"><stop stopColor="#fff2d8" /><stop offset="1" stopColor="#ba9e7d" /></radialGradient>
              </defs>
              <ellipse cx="315" cy="321" rx="205" ry="25" fill="#13182d" fillOpacity=".3" />
              <path d="M178 294V150a112 112 0 0 1 224 0v144Z" fill="url(#atelier-arch)" />
              <path d="M219 294V153a71 71 0 0 1 142 0v141Z" fill="url(#atelier-window)" />
              <circle cx="308" cy="157" r="27" fill="#f7e5bf" />
              <path d="m219 273 57-67 38 38 47-55v105H219Z" fill="#657f7c" />
              <path d="m219 283 91-38 51 37v12H219Z" fill="#a8bcb0" />
              <path d="m178 294 224 0 64 37H118Z" fill="url(#atelier-floor)" />
              <path d="M118 331h348v12H118Z" fill="#7d839f" />
              <path d="m145 343 294 0 41 20H102Z" fill="#a0a5be" />
              <path d="M102 363h378v7H102Z" fill="#727c98" />
              <circle cx="424" cy="272" r="39" fill="url(#atelier-orb)" />
              <path d="m134 111 4 13 13 4-13 4-4 13-4-13-13-4 13-4Z" fill="#c6c4e9" />
              <circle cx="446" cy="94" r="3" fill="#b5c6c6" />
              <path d="M102 228c-32-56 98-141 239-133 100 6 164 46 135 76" stroke="#c9c7e2" strokeOpacity=".25" strokeDasharray="3 7" />
            </svg>
            <span className="atelier-art__caption">A LITTLE IDEA. ENDLESS POSSIBILITIES.</span>
          </div>
          <div className="atelier-features" aria-label="平台主要功能">
            {creationFeatures.map(({ title, detail, icon: Icon }) => (
              <div className="atelier-feature" key={title}>
                <span className="atelier-feature__icon"><Icon size={18} aria-hidden="true" /></span>
                <div><h2>{title}</h2><p>{detail}</p></div>
              </div>
            ))}
          </div>
          <footer className="atelier-story__footer"><span>图片生成<span> / </span>视觉编辑<span> / </span>视频创作</span><ArrowUpRight size={18} /></footer>
        </div>
        <aside className="atelier-form" aria-label="账号登录与注册">{children}<p className="atelier-form__footnote">每一次创作，都从这里开始。</p></aside>
      </section>
    </main>
  );
};

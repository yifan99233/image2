import { type PropsWithChildren, useEffect, useState } from "react";
import { ArrowUpRight, Check, Code2, ImageIcon, Sparkles, WandSparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";

type AuthPageLayoutProps = PropsWithChildren;

const capabilities = [
  {
    title: "图片生成与编辑",
    icon: ImageIcon,
  },
  {
    title: "文生 / 图生视频",
    icon: WandSparkles,
  },
  {
    title: "Codex 定制版",
    icon: Code2,
  },
];

const workflowItems = [
  { title: "批量生成商品套图", meta: "6 张图片已完成", state: "已完成" },
  { title: "图生视频任务", meta: "正在生成第 2 个镜头", state: "生成中" },
  { title: "Codex API Key 用量", meta: "今日调用记录已同步", state: "已同步" },
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
    <main className="auth-page auth-page--simple">
      <header className="auth-landing-nav">
        <Link className="auth-page__brand" to="/login" onClick={(event) => event.preventDefault()}>
          <span className="brand__mark">
            <img src={siteConfig.site_icon_url || "/image2ai-icon.svg"} alt="" />
          </span>
          <span className="auth-brand__name">{siteConfig.site_name}</span>
        </Link>
        <span className="auth-nav-note">AI 创作与开发工作台</span>
      </header>

      <section className="auth-home" aria-label="产品登录首页">
        <div className="auth-home__content">
          <div className="auth-home__copy">
            <p className="auth-hero__eyebrow">
              <Sparkles size={15} />
              AI 视觉创作与开发工作台
            </p>
            <h1>
              <span>图片、视频与 Codex</span>
              <span>都在一个工作台</span>
            </h1>
            <p className="auth-home__summary">
              从文生图、批量改图到图生视频，再到 Codex 定制版接入，把创作与开发所需的 AI 能力集中在一起。
            </p>
          </div>

          <div className="auth-capability-list" aria-label="核心能力">
            {capabilities.map(({ title, icon: Icon }) => (
              <span key={title}>
                <Icon size={17} />
                {title}
              </span>
            ))}
          </div>

          <section className="auth-product-preview" aria-label="工作台预览">
            <header>
              <div>
                <span className="auth-preview__dot" />
                今日工作流
              </div>
              <span className="auth-preview__link">
                查看全部
                <ArrowUpRight size={14} />
              </span>
            </header>
            <div className="auth-workflow-list">
              {workflowItems.map((item, index) => (
                <article key={item.title}>
                  <span className={`auth-workflow-icon auth-workflow-icon--${index + 1}`}>
                    {index === 0 ? <Check size={16} /> : index + 1}
                  </span>
                  <div>
                    <h3>{item.title}</h3>
                    <p>{item.meta}</p>
                  </div>
                  <span className={`auth-workflow-state auth-workflow-state--${index + 1}`}>{item.state}</span>
                </article>
              ))}
            </div>
          </section>
        </div>

        <aside className="auth-workbench" aria-label="账号工作台">
          {children}
        </aside>
      </section>
    </main>
  );
};

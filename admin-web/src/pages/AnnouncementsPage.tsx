import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { Bell, Check, CheckCircle2, Cloud, HardDrive, Image as ImageIcon, Megaphone, RefreshCcw, Sparkles, UploadCloud } from "lucide-react";
import { createMaterialUploadToken, getSiteContentConfig, updateCurrentSiteContentConfig, uploadMaterialLocally } from "../services/adminApi";
import type { SiteConfig } from "../types";
import { PageChrome, useAutoDismissNotice } from "./management/ManagementCommon";

export function AnnouncementsPage() {
  const [form, setForm] = useState<SiteConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadMode, setUploadMode] = useState<"cdn" | "local">("cdn");
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useAutoDismissNotice(notice, setNotice);

  async function load() {
    setIsLoading(true);
    setError("");
    try {
      setForm(await getSiteContentConfig());
    } catch (err) {
      setError(err instanceof Error ? err.message : "公告配置接口不可用");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const announcement = form?.system_announcement;
  const imageUrl = announcement?.image_url?.trim() ?? "";

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  function updateAnnouncement(patch: Partial<NonNullable<SiteConfig["system_announcement"]>>) {
    setForm((current) => current ? {
      ...current,
      system_announcement: { ...current.system_announcement, ...patch },
    } : current);
  }

  async function uploadAnnouncementImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError("图片不能超过 10MB。");
      return;
    }
    if (file.type && !["image/jpeg", "image/png", "image/webp", "image/gif"].includes(file.type)) {
      setError("仅支持 JPG、PNG、WEBP、GIF 图片。");
      return;
    }

    setIsUploadingImage(true);
    setUploadStatus(uploadMode === "cdn" ? "正在获取 CDN 上传凭证..." : "正在上传到本地存储...");
    setError("");
    setNotice("");
    try {
      let imageUrl = "";
      if (uploadMode === "cdn") {
        const uploadToken = await createMaterialUploadToken(file.name, "image");
        const body = new FormData();
        body.append("token", uploadToken.token);
        body.append("key", uploadToken.key);
        body.append("file", file);
        setUploadStatus("正在上传到 CDN...");
        const response = await fetch(uploadToken.upload_url, { method: "POST", body });
        if (!response.ok) {
          const text = await response.text().catch(() => "");
          throw new Error(text || `CDN 上传失败（${response.status}）`);
        }
        imageUrl = uploadToken.public_url;
      } else {
        const result = await uploadMaterialLocally(file);
        imageUrl = result.public_url;
      }
      updateAnnouncement({ image_url: imageUrl });
      setNotice(`配图已上传到${uploadMode === "cdn" ? " CDN" : "本地存储"}，请保存公告后正式使用。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "配图上传失败");
    } finally {
      setIsUploadingImage(false);
      setUploadStatus("");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form || !announcement) return;
    if (announcement.is_enabled && !announcement.content.trim()) {
      setError("启用公告前，请填写公告内容。");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const saved = await updateCurrentSiteContentConfig({
        ...form,
        system_announcement: {
          ...announcement,
          title: announcement.title.trim(),
          content: announcement.content.trim(),
          image_url: imageUrl,
        },
      });
      setForm(saved);
      setNotice("公告已保存，用户端刷新后会读取最新公告。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "公告保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome
      title="系统公告"
      description="发布面向当前站点用户的公告。用户点击“我已阅读”后，本次公告不会再次提示；修改公告内容后会重新展示。"
      action={<button className="secondary-button compact" type="button" onClick={() => void load()} disabled={isLoading || isSubmitting}><RefreshCcw size={14} />重新读取</button>}
    >
      {error ? <section className="inline-state error"><Bell size={17} /><span>{error}</span></section> : null}
      {notice ? <div className="inline-state success"><CheckCircle2 size={17} /><span>{notice}</span></div> : null}
      {isLoading || !form || !announcement ? (
        <section className="panel inline-state">正在读取公告配置...</section>
      ) : (
        <section className="announcement-management-layout">
          <form className="panel announcement-editor" onSubmit={submit}>
            <div className="announcement-editor__heading">
              <div className="announcement-editor__icon"><Megaphone size={20} /></div>
              <div>
                <h3>编辑公告内容</h3>
                <p>{form.site_name} · 当前运营站点</p>
              </div>
            </div>
            <label className="announcement-switch">
              <span>
                <strong>向用户展示公告</strong>
                <small>{announcement.is_enabled ? "公告已启用，用户进入站点时会看到弹窗" : "公告未启用，保存后不会向用户展示"}</small>
              </span>
              <input type="checkbox" checked={announcement.is_enabled} onChange={(event) => updateAnnouncement({ is_enabled: event.target.checked })} />
            </label>
            <label className="field">
              公告标题
              <input value={announcement.title} maxLength={80} onChange={(event) => updateAnnouncement({ title: event.target.value })} placeholder="例如：系统维护通知" />
            </label>
            <label className="field">
              公告内容
              <textarea value={announcement.content} maxLength={2000} rows={8} onChange={(event) => updateAnnouncement({ content: event.target.value })} placeholder="填写需要向用户展示的通知内容，支持换行。" />
              <small>{announcement.content.length}/2000 字</small>
            </label>
            <div className="field announcement-image-uploader">
              <span className="field__label">公告配图（可选）</span>
              <div className="announcement-upload-mode" role="group" aria-label="配图上传方式">
                <button className={uploadMode === "cdn" ? "is-active" : ""} type="button" onClick={() => setUploadMode("cdn")} disabled={isUploadingImage}>
                  <Cloud size={15} />CDN 上传<span>推荐</span>
                </button>
                <button className={uploadMode === "local" ? "is-active" : ""} type="button" onClick={() => setUploadMode("local")} disabled={isUploadingImage}>
                  <HardDrive size={15} />本地上传
                </button>
              </div>
              <label className={`announcement-upload-dropzone ${isUploadingImage ? "is-uploading" : ""}`}>
                <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={uploadAnnouncementImage} disabled={isUploadingImage} />
                <UploadCloud size={22} />
                <strong>{isUploadingImage ? uploadStatus : "点击选择配图"}</strong>
                <small>支持 JPG、PNG、WEBP、GIF，单张不超过 10MB</small>
              </label>
              <label className="announcement-image-url-field">
                <span>或直接填写图片 URL</span>
                <input value={announcement.image_url ?? ""} maxLength={2048} onChange={(event) => updateAnnouncement({ image_url: event.target.value })} placeholder="https://.../announcement.png" />
              </label>
              <small>默认使用 CDN 上传；切换为本地上传后，图片会保存到当前环境的 MinIO。留空时使用默认插画。</small>
            </div>
            <div className="announcement-editor__actions">
              <span><Check size={15} />保存后用户端刷新即可读取</span>
              <button className="primary-button" type="submit" disabled={isSubmitting}>{isSubmitting ? "保存中..." : "保存公告"}</button>
            </div>
          </form>
          <aside className="panel announcement-preview-panel">
            <div className="announcement-preview-panel__heading"><span>实时预览</span><em className={announcement.is_enabled ? "is-active" : ""}>{announcement.is_enabled ? "展示中" : "未启用"}</em></div>
            <div className="announcement-preview-card">
              <div className="announcement-preview-card__visual">
                {imageUrl && !imageFailed ? <img src={imageUrl} alt="公告配图预览" onError={() => setImageFailed(true)} /> : (
                  <div className="announcement-preview-card__fallback"><Sparkles size={20} /><Megaphone size={34} /><span>NOTICE</span></div>
                )}
              </div>
              <div className="announcement-preview-card__body">
                <div className="announcement-preview-card__eyebrow"><span /> 系统公告</div>
                <h4>{announcement.title.trim() || "系统公告标题"}</h4>
                <p>{announcement.content.trim() || "公告内容会在这里预览。"}</p>
                <div className="announcement-preview-card__button">我已阅读</div>
              </div>
            </div>
            <div className="announcement-preview-panel__hint"><ImageIcon size={15} />用户端弹窗会使用同样的公告内容和配图</div>
          </aside>
        </section>
      )}
    </PageChrome>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Megaphone, Sparkles } from "lucide-react";
import type { SiteConfig, SystemAnnouncement } from "@/types/api";

type SystemAnnouncementModalProps = {
  siteConfig: SiteConfig;
  announcement: SystemAnnouncement;
  userId: number | null | undefined;
};

const storagePrefix = "image2ai:system-announcement-read";

export const SystemAnnouncementModal = ({ siteConfig, announcement, userId }: SystemAnnouncementModalProps) => {
  const [isOpen, setIsOpen] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const [hasReachedEnd, setHasReachedEnd] = useState(false);
  const [readHint, setReadHint] = useState("");
  const contentRef = useRef<HTMLParagraphElement>(null);
  const imageUrl = announcement.image_url?.trim() ?? "";
  const announcementKey = useMemo(
    () => JSON.stringify([siteConfig.site_key, announcement.title.trim(), announcement.content.trim(), imageUrl]),
    [announcement.content, announcement.title, imageUrl, siteConfig.site_key],
  );
  const storageKey = userId ? `${storagePrefix}:${siteConfig.site_key}:${userId}` : null;
  const isConfigured = announcement.is_enabled && Boolean(announcement.content.trim());

  useEffect(() => {
    setImageFailed(false);
  }, [imageUrl]);

  useEffect(() => {
    if (!storageKey || !isConfigured) {
      setIsOpen(false);
      return;
    }
    try {
      setIsOpen(window.localStorage.getItem(storageKey) !== announcementKey);
    } catch {
      setIsOpen(true);
    }
  }, [announcementKey, isConfigured, storageKey]);

  useEffect(() => {
    if (!isOpen) return;
    const frame = window.requestAnimationFrame(() => {
      const content = contentRef.current;
      if (!content) return;
      content.scrollTop = 0;
      setHasReachedEnd(content.scrollHeight <= content.clientHeight + 4);
      setReadHint("");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [announcementKey, isOpen]);

  if (!isOpen) return null;

  const updateReadProgress = () => {
    const content = contentRef.current;
    if (!content) return;
    const reachedEnd = content.scrollHeight <= content.clientHeight + 4
      || content.scrollTop + content.clientHeight >= content.scrollHeight - 4;
    setHasReachedEnd(reachedEnd);
    if (reachedEnd) setReadHint("");
  };

  const handleReadButton = () => {
    if (!hasReachedEnd) {
      const content = contentRef.current;
      content?.scrollTo({ top: content.scrollHeight, behavior: "smooth" });
      setReadHint("请阅读完公告内容后再确认");
      return;
    }
    if (storageKey) {
      try {
        window.localStorage.setItem(storageKey, announcementKey);
      } catch {
        // A private browsing policy can reject localStorage. The current view
        // still closes, and the announcement will be eligible again later.
      }
    }
    setIsOpen(false);
  };

  return (
    <div className="system-announcement-modal__backdrop" role="presentation">
      <section
        className="system-announcement-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="system-announcement-title"
        aria-describedby="system-announcement-content"
      >
        <div className="system-announcement-modal__visual" aria-hidden="true">
          {imageUrl && !imageFailed ? (
            <img src={imageUrl} alt="" onError={() => setImageFailed(true)} />
          ) : (
            <div className="system-announcement-modal__illustration">
              <div className="system-announcement-modal__illustration-orbit" />
              <div className="system-announcement-modal__illustration-card">
                <Megaphone size={42} strokeWidth={1.7} />
                <Sparkles className="system-announcement-modal__illustration-sparkle" size={19} />
                <span>NEW</span>
              </div>
            </div>
          )}
          <div className="system-announcement-modal__visual-caption">艺源 · 最新通知</div>
        </div>
        <div className="system-announcement-modal__body">
          <div className="system-announcement-modal__eyebrow"><span /> 系统公告</div>
          <h2 id="system-announcement-title">{announcement.title.trim() || "系统公告"}</h2>
          <p id="system-announcement-content" ref={contentRef} onScroll={updateReadProgress}>{announcement.content}</p>
          <div className="system-announcement-modal__footer">
            <span className={readHint ? "is-warning" : ""} aria-live="polite"><Check size={15} /> {readHint || "请滑动阅读完整公告后确认"}</span>
            <button className="primary-button" type="button" onClick={handleReadButton}>我知道了</button>
          </div>
        </div>
      </section>
    </div>
  );
};

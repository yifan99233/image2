import { useEffect, useState, type FormEvent } from "react";
import {
  Check,
  CheckCircle2,
  BellRing,
  Copy,
  Gift,
  Headphones,
  Link as LinkIcon,
  Loader2,
  LockKeyhole,
  MessageCircle,
  MessageSquareText,
  Play,
  UploadCloud,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { feedbackService } from "@/services/feedback";
import { inviteService } from "@/services/invite";
import { leadService } from "@/services/leads";
import { rewardService } from "@/services/rewards";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import { uploadService } from "@/services/uploads";
import type { ImageAsset, InviteRewardConfig, InviteSummary, LeadModuleStatus, LeadTrialApplication, LeadTrialApplicationInput, SigninStatus, SiteConfig, UserFeedback } from "@/types/api";
import { hasConfiguredMaterial, hasConfiguredVideo } from "@/pages/shared/mediaConfig";
import { ConfiguredMedia, VideoPreviewModal } from "@/pages/shared/mediaPreview";
import { resolveAssetUrl } from "@/utils/assets";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";
import { formatDateTime } from "@/utils/time";

const leadTrialStatusLabel: Record<LeadTrialApplication["status"], string> = {
  pending: "待处理",
  processing: "处理中",
  approved: "已开通",
  rejected: "暂不适配",
};

export { CreativeToolPage, ProductToolPage } from "@/pages/tools/ToolPages";
export { GrokImaginePage } from "@/pages/tools/GrokImaginePage";
export { DashboardPage, GalleryPage } from "@/pages/showcase/ShowcasePages";

export const SupportPage = () => {
  const [copied, setCopied] = useState<"qq" | "wechat" | null>(null);
  const [siteConfig, setSiteConfig] = useState<SiteConfig>(readCachedSiteConfig);
  const qqNumber = siteConfig.support_qq;
  const wechatId = siteConfig.support_wechat;
  const wechatQrcodeUrl = siteConfig.support_wechat_qrcode_url || "/wechat-qrcode.png";
  const qqChatUrl = `https://wpa.qq.com/msgrd?v=3&uin=${qqNumber}&site=qq&menu=yes`;

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  const copyContact = async (type: "qq" | "wechat", value: string) => {
    await navigator.clipboard.writeText(value);
    setCopied(type);
    window.setTimeout(() => setCopied(null), 1600);
  };

  return (
    <main className="page-surface">
      <section className="support-shell">
        <header className="support-hero">
          <div className="utility-icon">
            <Headphones size={24} />
          </div>
          <div>
            <span className="invite-kicker">联系客服</span>
            <h1>遇到问题，直接联系人工客服</h1>
            <p>模型调用、充值积分、任务失败或账号问题，都可以通过下面方式联系。</p>
          </div>
        </header>

        <div className="support-contact-grid">
          <article className="support-contact-card support-contact-card--qr">
            <div className="support-contact-card__main">
              <span>微信客服</span>
              <strong>扫码添加</strong>
              <p>开通客资模块或处理账号问题，请扫码添加微信。</p>
            </div>
            <img className="support-qrcode" src={wechatQrcodeUrl} alt="微信客服二维码" />
          </article>

          {qqNumber ? <article className="support-contact-card">
            <div className="support-contact-card__main">
              <span>QQ 客服</span>
              <strong>{qqNumber}</strong>
              <p>直接打开 QQ 会话，或复制号码后手动添加。</p>
            </div>
            <div className="support-actions">
              <a className="support-action support-action--primary" href={qqChatUrl} target="_blank" rel="noreferrer">
                <MessageCircle size={16} />
                打开 QQ
              </a>
              <Button type="button" variant="secondary" className="support-action" onClick={() => copyContact("qq", qqNumber)}>
                {copied === "qq" ? <Check size={16} /> : <Copy size={16} />}
                {copied === "qq" ? "已复制" : "复制 QQ"}
              </Button>
            </div>
          </article> : null}

          {wechatId ? <article className="support-contact-card">
            <div className="support-contact-card__main">
              <span>微信客服</span>
              <strong>{wechatId}</strong>
              <p>添加时备注{siteConfig.site_name}和账号信息，方便快速定位问题。</p>
            </div>
            <div className="support-actions">
              <Button type="button" variant="secondary" className="support-action" onClick={() => copyContact("wechat", wechatId)}>
                {copied === "wechat" ? <Check size={16} /> : <Copy size={16} />}
                {copied === "wechat" ? "已复制" : "复制微信号"}
              </Button>
            </div>
          </article> : null}
        </div>
      </section>
    </main>
  );
};

export const LeadModulePage = () => {
  const [status, setStatus] = useState<LeadModuleStatus | null>(null);
  const [siteConfig, setSiteConfig] = useState<SiteConfig>(readCachedSiteConfig);
  const [credentials, setCredentials] = useState<{ enterprise_account: string; enterprise_password: string } | null>(null);
  const [trialForm, setTrialForm] = useState<LeadTrialApplicationInput>({
    business_scope: "",
    keywords: "",
    competitor_accounts: "",
    contact_info: "",
  });
  const [latestApplication, setLatestApplication] = useState<LeadTrialApplication | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isRevealing, setIsRevealing] = useState(false);
  const [isSubmittingApplication, setIsSubmittingApplication] = useState(false);
  const [previewVideo, setPreviewVideo] = useState<{ title: string; url: string; poster?: string } | null>(null);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    leadService
      .getModuleStatus()
      .then((nextStatus) => {
        if (!ignore) {
          setStatus(nextStatus);
          setError("");
        }
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "客资模块状态加载失败");
      });
    leadService
      .getLatestTrialApplication()
      .then((application) => {
        if (!ignore) setLatestApplication(application);
      })
      .catch(() => {
        if (!ignore) setLatestApplication(null);
      });
    return () => {
      ignore = true;
    };
  }, []);

  const leadSystemUrl = status?.enterprise_id
    ? `https://note.shyfai.cn/login?redirect=${encodeURIComponent(status.enterprise_id)}`
    : "https://note.shyfai.cn/login";
  const visibleLeadCases = siteConfig.lead_case_materials.filter(hasConfiguredMaterial);

  useEffect(() => {
    if (!previewVideo) return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewVideo(null);
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [previewVideo]);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  async function revealCredentials() {
    setError("");
    setNotice("");
    setIsRevealing(true);
    try {
      const nextCredentials = await leadService.revealCredentials();
      setCredentials({
        enterprise_account: nextCredentials.enterprise_account,
        enterprise_password: nextCredentials.enterprise_password,
      });
      setStatus((current) =>
        current
          ? {
              ...current,
              can_reveal_credentials: false,
              credentials_revealed_at: nextCredentials.credentials_revealed_at,
            }
          : current,
      );
      setNotice("企业账号和密码已展示，本次关闭或刷新后不会再次显示。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "企业账号密码读取失败");
    } finally {
      setIsRevealing(false);
    }
  }

  async function submitTrialApplication(event: FormEvent) {
    event.preventDefault();
    const nextForm = {
      business_scope: trialForm.business_scope.trim(),
      keywords: trialForm.keywords.trim(),
      competitor_accounts: trialForm.competitor_accounts.trim(),
      contact_info: trialForm.contact_info.trim(),
    };
    if (!nextForm.contact_info) {
      setError("请填写联系方式");
      return;
    }

    setError("");
    setNotice("");
    setIsSubmittingApplication(true);
    try {
      const application = await leadService.submitTrialApplication(nextForm);
      setLatestApplication(application);
      setTrialForm({
        business_scope: "",
        keywords: "",
        competitor_accounts: "",
        contact_info: "",
      });
      setNotice("申请已提交，管理员会根据行业关键词和对标账号确认适配方案。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "申请提交失败");
    } finally {
      setIsSubmittingApplication(false);
    }
  }

  return (
    <main className="page-surface">
      <section className="lead-module-shell">
        {!status?.is_enabled ? (
          <header className="lead-module-hero">
            <div className="utility-icon">
              <LockKeyhole size={26} />
            </div>
            <div>
              <span className="invite-kicker">AI高效精准获客</span>
              <h1>AI高效精准获客</h1>
              <p>该模块仅针对业务需求匹配用户开放（如需了解该模块，请添加下方管理员）。</p>
            </div>
          </header>
        ) : null}

        {error ? <div className="list-state list-state--error">{error}</div> : null}
        {notice ? <div className="inline-result"><CheckCircle2 size={17} />{notice}</div> : null}
        {!status && !error ? <div className="list-state">正在读取客资模块开通状态...</div> : null}

        {visibleLeadCases.length ? <section className="lead-video-section" aria-label="行业视频案例">
          <div className="dash-section__head">
            <h2>当前垂类行业视频案例</h2>
            <span>家具、大健康、珠宝、考公等获客场景</span>
          </div>
          <div className="lead-video-grid">
            {visibleLeadCases.map((item, index) => {
              const videoUrl = resolveAssetUrl(item.file_url || "");
              const coverUrl = item.cover_url ? resolveAssetUrl(item.cover_url) : undefined;
              const isVideo = hasConfiguredVideo(item);
              return (
              <article className="lead-video-card" key={item.title}>
                <button
                  className="lead-video-card__screen"
                  disabled={!isVideo}
                  onClick={() => isVideo && setPreviewVideo({ title: item.title, url: videoUrl, poster: coverUrl })}
                  type="button"
                >
                  <ConfiguredMedia item={item} className="lead-video-card__media" />
                  {isVideo ? <Play size={24} /> : null}
                  <span className="lead-video-card__index">{String(index + 1).padStart(2, "0")}</span>
                  {isVideo ? <span className="video-click-hint">点击预览</span> : null}
                </button>
                <strong>{item.title}</strong>
                <p>{item.subtitle}</p>
              </article>
            );
            })}
          </div>
        </section> : null}

        {status && !status.is_enabled ? (
          <section className="lead-application-panel">
            <form className="lead-application-form" onSubmit={submitTrialApplication}>
              <div className="lead-application-form__head">
                <span className="invite-kicker">申请试用</span>
                <h2>提交行业信息，申请开通客资模块</h2>
                <p>关键词越能直接搜出行业相关帖子，采集结果越精准；过泛的词会降低匹配质量。</p>
              </div>
              {latestApplication ? (
                <div className="lead-application-status">
                  <CheckCircle2 size={17} />
                  <span>最近申请：{leadTrialStatusLabel[latestApplication.status]}{latestApplication.created_at ? ` · ${formatDateTime(latestApplication.created_at)}` : ""}</span>
                </div>
              ) : null}
              <label className="lead-form-field">
                <span>业务背景、范围描述</span>
                <textarea
                  value={trialForm.business_scope}
                  onChange={(event) => setTrialForm((current) => ({ ...current, business_scope: event.target.value }))}
                  placeholder="你是做什么业务的，主要卖哪些产品，目标客户是谁"
                  rows={4}
                />
              </label>
              <label className="lead-form-field">
                <span>小红书/抖音高命中关键词</span>
                <textarea
                  value={trialForm.keywords}
                  onChange={(event) => setTrialForm((current) => ({ ...current, keywords: event.target.value }))}
                  placeholder="一行一个关键词，例如：谷子、吧唧、吃谷、谷圈周边"
                  rows={4}
                />
              </label>
              <label className="lead-form-field">
                <span>十个对标同行账号名称</span>
                <textarea
                  value={trialForm.competitor_accounts}
                  onChange={(event) => setTrialForm((current) => ({ ...current, competitor_accounts: event.target.value }))}
                  placeholder="一行一个账号名称，最多填写 10 个"
                  rows={4}
                />
              </label>
              <label className="lead-form-field">
                <span>联系方式</span>
                <input
                  value={trialForm.contact_info}
                  onChange={(event) => setTrialForm((current) => ({ ...current, contact_info: event.target.value }))}
                  placeholder="微信、手机号或其他可联系信息"
                />
              </label>
              <Button type="submit" disabled={isSubmittingApplication} isLoading={isSubmittingApplication}>
                提交申请试用
              </Button>
            </form>
            <aside className="lead-application-contact">
              <img className="lead-module-qr" src={siteConfig.support_wechat_qrcode_url || "/wechat-qrcode.png"} alt="微信客服二维码" />
              <strong>也可以联系客服</strong>
              <p>提交表单后后台会同步生成申请记录；需要补充资料时可通过客服沟通。</p>
              <Link className="button button--secondary" to="/support">联系客服</Link>
            </aside>
          </section>
        ) : null}

        {status?.is_enabled ? (
          <>
            <section className="lead-module-entry">
              <div>
                <span className="invite-kicker">AI高效精准获客</span>
                <h1>AI高效精准获客已开通</h1>
              </div>
              <a className="button button--primary" href={leadSystemUrl} target="_blank" rel="noreferrer">
                进入客资系统
              </a>
            </section>
            <section className="lead-module-grid">
              <article className="lead-module-card lead-module-card--identity">
                <span>企业 ID</span>
                <strong>{status.enterprise_id}</strong>
              </article>
              {credentials ? (
                <>
                  <article className="lead-module-card">
                    <span>企业账号</span>
                    <strong>{credentials.enterprise_account}</strong>
                  </article>
                  <article className="lead-module-card">
                    <span>企业密码</span>
                    <strong>{credentials.enterprise_password}</strong>
                    <p>账号和密码只展示本次，请立即保存。</p>
                  </article>
                </>
              ) : (
                <article className="lead-module-card lead-module-card--credentials">
                  <div className="lead-module-card__content">
                    <span>企业账号和密码</span>
                    <strong>{status.can_reveal_credentials ? "待查看" : "已展示"}</strong>
                    <p>
                      {status.can_reveal_credentials
                        ? "账号和密码只展示一次，点击后服务端会记录展示时间。"
                        : "账号和密码已展示过；如需重置请联系管理员。"}
                    </p>
                  </div>
                  {status.can_reveal_credentials ? (
                    <Button type="button" disabled={isRevealing} isLoading={isRevealing} onClick={() => void revealCredentials()}>
                      查看一次账号密码
                    </Button>
                  ) : null}
                </article>
              )}
            </section>
          </>
        ) : null}
        <VideoPreviewModal preview={previewVideo} onClose={() => setPreviewVideo(null)} />
      </section>
    </main>
  );
};

export const SigninPage = () => {
  const [status, setStatus] = useState<SigninStatus | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadStatus = async () => {
    try {
      const nextStatus = await rewardService.getSigninStatus();
      setStatus(nextStatus);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "签到状态加载失败");
    }
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  const submitSignin = async () => {
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const result = await rewardService.signin();
      setNotice(`签到成功，获得 ${result.awarded_credits} 积分`);
      notifyCreditBalanceChanged();
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "签到失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (error && !status) {
    return (
      <main className="page-surface">
        <section className="utility-shell">
          <div className="utility-icon"><Gift size={30} /></div>
          <div>
            <h1>签到领积分</h1>
            <p>{error}</p>
          </div>
        </section>
      </main>
    );
  }

  if (!status) {
    return (
      <main className="page-surface">
        <section className="utility-shell">
          <div className="utility-icon"><Loader2 className="spin-icon" size={30} /></div>
          <div>
            <h1>签到领积分</h1>
            <p>正在读取后台签到配置。</p>
          </div>
        </section>
      </main>
    );
  }

  if (!status.is_enabled) {
    return (
      <main className="page-surface">
        <section className="utility-shell">
          <div className="utility-icon"><Gift size={30} /></div>
          <div>
            <h1>签到领积分</h1>
            <p>当前每日签到功能未开启。</p>
          </div>
          <div className="empty-state">
            <BellRing size={34} />
            <h3>活动暂未开放</h3>
            <p>后台开启签到并配置每日积分后，这里会展示签到按钮和签到记录。</p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="page-surface">
      <section className="invite-shell">
        <header className="invite-hero">
          <div>
            <span className="invite-kicker"><Gift size={16} />签到领积分</span>
            <h1>每日签到，领取 {status.daily_credits} 积分</h1>
            <p>每个账号按自然日只能成功签到一次，重复请求会由后端拦截。</p>
          </div>
          <div className="invite-code-card">
            <span>连续签到</span>
            <strong>{status.current_streak} 天</strong>
          </div>
        </header>

        <div className="invite-rule-grid">
          <article>
            <span>今日奖励</span>
            <strong>{status.daily_credits} 积分</strong>
            <p>{status.today_signed ? "今日已领取，明天再来。" : "点击签到后立即进入积分余额。"}</p>
          </article>
          <article>
            <span>累计签到</span>
            <strong>{status.total_signins} 次</strong>
            <p>{status.last_sign_date ? `最近签到：${status.last_sign_date}` : "还没有签到记录。"}</p>
          </article>
        </div>

        <section className="invite-link-panel">
          <div>
            <span>今日状态</span>
            <strong>{status.today_signed ? "已签到" : "可签到"}</strong>
          </div>
          <Button type="button" disabled={status.today_signed} isLoading={isSubmitting} onClick={submitSignin}>
            <CheckCircle2 size={16} />
            {status.today_signed ? "今日已签到" : "立即签到"}
          </Button>
        </section>

        {notice ? <section className="signin-message signin-message--success">{notice}</section> : null}
        {error ? <section className="signin-message signin-message--error">{error}</section> : null}

        <section className="signin-records">
          <div className="section-heading">
            <h2>最近签到记录</h2>
            <p>这里只展示后端返回的真实签到记录。</p>
          </div>
          {status.recent_records.length === 0 ? (
            <div className="empty-state">
              <Gift size={34} />
              <h3>暂无签到记录</h3>
              <p>完成首次签到后，记录会展示在这里。</p>
            </div>
          ) : status.recent_records.map((record) => (
            <article className="signin-record-row" key={record.id}>
              <div>
                <strong>{record.sign_date}</strong>
                <span>连续 {record.streak_days} 天 · {formatDateTime(record.created_at)}</span>
              </div>
              <b>+{record.awarded_credits}</b>
            </article>
          ))}
        </section>
      </section>
    </main>
  );
};

export const InvitePage = () => {
  const [config, setConfig] = useState<InviteRewardConfig | null>(null);
  const [summary, setSummary] = useState<InviteSummary | null>(null);
  const [error, setError] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    let ignore = false;
    Promise.all([inviteService.getRewardConfig(), inviteService.getSummary()])
      .then(([nextConfig, nextSummary]) => {
        if (!ignore) {
          setConfig(nextConfig);
          setSummary(nextSummary);
          setError("");
        }
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "邀请奖励配置加载失败");
      });
    return () => {
      ignore = true;
    };
  }, []);

  const copyInviteUrl = async () => {
    if (!config?.invite_url) return;
    try {
      await navigator.clipboard.writeText(config.invite_url);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  if (error) {
    return (
      <main className="page-surface">
        <section className="utility-shell">
          <div className="utility-icon"><LinkIcon size={30} /></div>
          <div>
            <h1>邀请赚积分</h1>
            <p>{error}</p>
          </div>
        </section>
      </main>
    );
  }

  if (!config) {
    return (
      <main className="page-surface">
        <section className="utility-shell">
          <div className="utility-icon"><Loader2 className="spin-icon" size={30} /></div>
          <div>
            <h1>邀请赚积分</h1>
            <p>正在读取后台邀请奖励配置。</p>
          </div>
        </section>
      </main>
    );
  }

  if (!config.is_enabled) {
    return (
      <main className="page-surface">
        <section className="utility-shell">
          <div className="utility-icon"><LinkIcon size={30} /></div>
          <div>
            <h1>邀请赚积分</h1>
            <p>当前邀请奖励活动未开启。</p>
          </div>
          <div className="empty-state">
            <BellRing size={34} />
            <h3>活动暂未开放</h3>
            <p>后台开启邀请奖励后，这里会展示邀请码、邀请链接和奖励规则。</p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="page-surface">
      <section className="invite-shell">
        <header className="invite-hero">
          <div>
            <span className="invite-kicker"><Gift size={16} />邀请赚积分</span>
            <h1>邀请有效用户，持续获得积分奖励</h1>
            <p>{config.valid_user_rule_label}。后续被邀请用户充值时，按后台配置比例继续奖励。</p>
          </div>
          <div className="invite-code-card">
            <span>我的邀请码</span>
            <strong>{config.invite_code}</strong>
          </div>
        </header>

        <div className="invite-rule-grid">
          <article>
            <span>有效用户奖励</span>
            <strong>{config.valid_user_reward_credits} 积分</strong>
            <p>邀请用户完成首次付费充值后发放。</p>
          </article>
          <article>
            <span>后续充值奖励</span>
            <strong>{config.recharge_reward_percent}%</strong>
            <p>按被邀请用户后续充值到账积分比例奖励。</p>
          </article>
          <article>
            <span>已邀请用户</span>
            <strong>{summary?.total_invitees ?? 0} 人</strong>
            <p>{summary?.valid_invitees ?? 0} 个有效用户。</p>
          </article>
          <article>
            <span>已获得返利</span>
            <strong>{summary?.total_reward_credits ?? 0} 积分</strong>
            <p>来自真实邀请奖励流水。</p>
          </article>
        </div>

        <section className="invite-link-panel">
          <div>
            <span>邀请链接</span>
            <strong>{config.invite_url}</strong>
          </div>
          <Button type="button" onClick={copyInviteUrl}>
            <Copy size={16} />
            {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制链接"}
          </Button>
        </section>

        <section className="invite-data-panel">
          <div className="section-heading">
            <h2>已邀请用户</h2>
            <p>展示通过你的邀请码注册的真实用户。</p>
          </div>
          {!summary?.invitees.length ? (
            <div className="empty-state">
              <Gift size={34} />
              <h3>暂无邀请用户</h3>
              <p>复制邀请链接给新用户注册后，会显示在这里。</p>
            </div>
          ) : summary.invitees.map((invitee) => (
            <article className="invite-data-row" key={invitee.id}>
              <div>
                <strong>{invitee.username}</strong>
                <span>{invitee.email} · 注册于 {formatDateTime(invitee.registered_at)}</span>
              </div>
              <div>
                <b>{invitee.total_recharged} 积分</b>
                <em>{invitee.is_valid ? "有效用户" : "未充值"}</em>
              </div>
            </article>
          ))}
        </section>

        <section className="invite-data-panel">
          <div className="section-heading">
            <h2>充值返还积分明细</h2>
            <p>展示已入账的邀请奖励积分流水。</p>
          </div>
          {!summary?.rewards.length ? (
            <div className="empty-state">
              <Gift size={34} />
              <h3>暂无返利明细</h3>
              <p>被邀请用户触发奖励后，返还积分会记录在这里。</p>
            </div>
          ) : summary.rewards.map((reward) => (
            <article className="invite-data-row" key={reward.id}>
              <div>
                <strong>{reward.description || "邀请奖励"}</strong>
                <span>{formatDateTime(reward.created_at)}{reward.biz_id ? ` · ${reward.biz_id}` : ""}</span>
              </div>
              <div>
                <b>+{reward.amount}</b>
                <em>余额 {reward.balance_after}</em>
              </div>
            </article>
          ))}
        </section>
      </section>
    </main>
  );
};

export { DeveloperApiPage, LicensePage, OpenAgentInstallPage, OpenAgentUsagePage, TeamPage } from "@/pages/opencode/OpenCodePages";
export { OpenAgentKeysPage } from "@/pages/opencode/OpenAgentKeysPage";

const feedbackStatusLabel: Record<UserFeedback["status"], string> = {
  pending: "待处理",
  processing: "处理中",
  resolved: "已解决",
  closed: "已关闭",
};

export const FeedbackPage = () => {
  const [description, setDescription] = useState("");
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [items, setItems] = useState<UserFeedback[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function load() {
    try {
      const result = await feedbackService.list(1, 10);
      setItems(result.items);
    } catch {
      setItems([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  async function uploadImages(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    const nextFiles = Array.from(files);
    if (images.length + nextFiles.length > 4) {
      setError("反馈图片最多上传 4 张");
      return;
    }
    setIsUploading(true);
    try {
      const uploaded: ImageAsset[] = [];
      for (const file of nextFiles) {
        uploaded.push(await uploadService.uploadImage(file));
      }
      setImages((current) => [...current, ...uploaded].slice(0, 4));
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片上传失败");
    } finally {
      setIsUploading(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const normalizedDescription = description.trim();
    if (!normalizedDescription) {
      setError("请填写反馈描述");
      return;
    }
    setError("");
    setNotice("");
    setIsSubmitting(true);
    try {
      await feedbackService.create(normalizedDescription, images.map((image) => image.id));
      setDescription("");
      setImages([]);
      setNotice("反馈已提交，后台会尽快处理。");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "反馈提交失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="page-surface">
      <section className="feedback-shell">
        <header className="support-hero">
          <div className="utility-icon">
            <MessageSquareText size={24} />
          </div>
          <div>
            <span className="invite-kicker">用户反馈</span>
            <h1>提交问题或建议</h1>
            <p>请描述你遇到的问题，也可以上传最多 4 张截图，方便后台定位。</p>
          </div>
        </header>

        <form className="feedback-form" onSubmit={submit}>
          <label className="field">
            文本描述
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={7} maxLength={2000} placeholder="请写清楚页面、操作步骤、异常现象或建议内容" />
            <small>{description.trim().length}/2000</small>
          </label>
          <label className="feedback-upload-zone">
            <UploadCloud size={22} />
            <span>{isUploading ? "上传中..." : "上传截图"}</span>
            <small>最多 4 张，支持 JPG、PNG、WEBP</small>
            <input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={isUploading || images.length >= 4} onChange={(event) => void uploadImages(event.target.files)} />
          </label>
          {images.length ? (
            <div className="feedback-image-grid">
              {images.map((image) => (
                <div className="feedback-image-card" key={image.id}>
                  <img src={resolveAssetUrl(image.url)} alt="反馈截图" />
                  <button type="button" aria-label="移除截图" onClick={() => setImages((current) => current.filter((item) => item.id !== image.id))}><X size={15} /></button>
                </div>
              ))}
            </div>
          ) : null}
          {error ? <div className="list-state list-state--error">{error}</div> : null}
          {notice ? <div className="inline-result"><CheckCircle2 size={17} />{notice}</div> : null}
          <div className="support-actions">
            <Button type="submit" disabled={isSubmitting || isUploading}>
              <Check size={16} />
              {isSubmitting ? "提交中..." : "提交反馈"}
            </Button>
          </div>
        </form>

        <section className="feedback-history">
          <h2>我的反馈</h2>
          {items.length ? items.map((item) => (
            <article className="feedback-history-item" key={item.id}>
              <div>
                <span className={`status-badge status-badge--${item.status}`}>{feedbackStatusLabel[item.status]}</span>
                <time>{item.created_at ? formatDateTime(item.created_at) : "-"}</time>
              </div>
              <p>{item.description}</p>
              {item.admin_remark ? <small>处理备注：{item.admin_remark}</small> : null}
            </article>
          )) : <div className="empty-state"><MessageSquareText size={34} /><h3>暂无反馈</h3><p>提交后可以在这里查看处理状态。</p></div>}
        </section>
      </section>
    </main>
  );
};

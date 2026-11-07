import { type FormEvent, useEffect, useState } from "react";
import { X } from "lucide-react";
import { formatCurrency, formatDateTime } from "../../lib/format";
import {
  createAdminAccount,
  createModelPricesBatch,
  discoverProviderModels,
  getActiveModelPrices,
  getImageSpecs,
  getUserLeadModule,
  saveModel,
  saveRechargePlan,
  saveUserLeadModule,
  updateAdminAccount,
  updateFeedback,
  updateModelSpecs,
} from "../../services/adminApi";
import type {
  AdminAccountInput,
  AdminOpenAPIKey,
  AdminImageModel,
  AdminImageModelInput,
  AdminRole,
  AdminUser,
  ImageSpecs,
  ManagedUser,
  RechargePlan,
  UserFeedback,
  UserFeedbackStatus,
  UserLeadModule,
  UserLeadModuleInput,
} from "../../types";
import { activePriceCellValues, changedModelPriceEntries, isModelPriceCellChanged, modelPriceCellKey, type PriceCellValues } from "../../lib/modelPriceMatrix";

const adminRoleLabel: Record<AdminRole, string> = {
  super_admin: "超级管理员",
  operator: "运营管理员",
  finance: "财务管理员",
  model_admin: "模型管理员",
};

const feedbackStatusOptions: Array<{ value: "all" | UserFeedbackStatus; label: string }> = [
  { value: "all", label: "全部状态" },
  { value: "pending", label: "待处理" },
  { value: "processing", label: "处理中" },
  { value: "resolved", label: "已解决" },
  { value: "closed", label: "已关闭" },
];

export type DialogState =
  | { kind: "none" }
  | { kind: "confirm"; title: string; body: string; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<void> | void }
  | { kind: "adminAccount"; account?: AdminUser }
  | { kind: "leadModule"; user: ManagedUser }
  | { kind: "feedback"; feedback: UserFeedback }
  | { kind: "plan"; plan?: RechargePlan }
  | { kind: "model"; model?: AdminImageModel }
  | { kind: "modelSpecs"; model: AdminImageModel }
  | { kind: "price"; models: AdminImageModel[] }
  | { kind: "reason"; title: string; body: string; confirmLabel: string; onConfirm: (reason: string) => Promise<void> | void };

export function Dialog({ state, onClose, afterDone }: { state: DialogState; onClose: () => void; afterDone: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setReason("");
    setError("");
    setIsSubmitting(false);
  }, [state.kind]);

  if (state.kind === "none") return null;

  async function submit(action: () => Promise<void> | void) {
    setIsSubmitting(true);
    setError("");
    try {
      await action();
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (state.kind === "confirm") {
    return (
      <div className="modal-backdrop" role="dialog" aria-modal="true">
        <div className="modal">
          <button className="modal-close" onClick={onClose} aria-label="关闭"><X size={18} /></button>
          <h3>{state.title}</h3>
          <p>{state.body}</p>
          {error && <div className="form-error">{error}</div>}
          <div className="modal-actions">
            <button className="secondary-button" onClick={onClose}>取消</button>
            <button className={state.danger ? "danger-button" : "primary-button"} disabled={isSubmitting} onClick={() => submit(state.onConfirm)}>
              {state.confirmLabel}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (state.kind === "reason") {
    return (
      <div className="modal-backdrop" role="dialog" aria-modal="true">
        <form className="modal" onSubmit={(event) => { event.preventDefault(); if (!reason.trim()) setError("必须填写原因"); else void submit(() => state.onConfirm(reason)); }}>
          <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
          <h3>{state.title}</h3>
          <p>{state.body}</p>
          <label className="field">原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} /></label>
          {error && <div className="form-error">{error}</div>}
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={onClose}>取消</button>
            <button className="primary-button" disabled={isSubmitting}>{state.confirmLabel}</button>
          </div>
        </form>
      </div>
    );
  }

  if (state.kind === "leadModule") {
    return <LeadModuleDialog user={state.user} onClose={onClose} afterDone={afterDone} />;
  }

  if (state.kind === "feedback") {
    return <FeedbackDialog feedback={state.feedback} onClose={onClose} afterDone={afterDone} />;
  }

  if (state.kind === "adminAccount") {
    return <AdminAccountDialog account={state.account} onClose={onClose} afterDone={afterDone} />;
  }

  if (state.kind === "plan") {
    return <PlanDialog plan={state.plan} onClose={onClose} afterDone={afterDone} />;
  }

  if (state.kind === "model") {
    return <ModelDialog model={state.model} onClose={onClose} afterDone={afterDone} />;
  }

  if (state.kind === "modelSpecs") {
    return <ModelSpecsDialog model={state.model} onClose={onClose} afterDone={afterDone} />;
  }

  if (state.kind === "price") {
    return <PriceDialog models={state.models} onClose={onClose} afterDone={afterDone} />;
  }

  return null;
}

function AdminAccountDialog({ account, onClose, afterDone }: { account?: AdminUser; onClose: () => void; afterDone: () => void }) {
  const [form, setForm] = useState<AdminAccountInput>({
    username: account?.username ?? "",
    email: account?.email ?? "",
    password: "",
    role: account?.role ?? "operator",
    is_active: account?.is_active ?? true,
    create_openapi_key: false,
    openapi_key_name: "",
    openapi_scopes: ["openagent:upload-token", "openagent:release:write"],
  });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createdOpenAPIKey, setCreatedOpenAPIKey] = useState<AdminOpenAPIKey | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const username = form.username.trim();
    const email = form.email.trim();
    if (username.length < 3) {
      setError("账号至少 3 个字符");
      return;
    }
    if (!email.includes("@")) {
      setError("请输入有效邮箱");
      return;
    }
    if (!account && form.password.length < 8) {
      setError("初始密码至少 8 个字符");
      return;
    }
    if (account && form.password.trim() && form.password.trim().length < 8) {
      setError("重置密码至少 8 个字符");
      return;
    }

    setError("");
    setIsSubmitting(true);
    try {
      if (account) {
        await updateAdminAccount(account.id, { ...form, username, email, password: form.password.trim() || undefined });
        afterDone();
        onClose();
      } else {
        const created = await createAdminAccount({ ...form, username, email });
        afterDone();
        if (created.openapi_key?.api_key) {
          setCreatedOpenAPIKey(created.openapi_key);
          return;
        }
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : account ? "编辑管理员账号失败" : "创建管理员账号失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>{account ? "编辑管理员账号" : "新增管理员账号"}</h3>
        <p>{account ? "修改后台账号资料、角色、启用状态；密码留空则不重置。" : "创建可登录后台的 admin 账号。角色会影响菜单和操作权限。"}</p>
        {createdOpenAPIKey ? (
          <section className="inline-state success">
            <span>API 用户已创建。明文 Key 只显示一次：{createdOpenAPIKey.api_key}</span>
          </section>
        ) : null}
        <div className="form-grid">
          <label className="field">账号<input value={form.username} onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))} autoComplete="off" /></label>
          <label className="field">邮箱<input value={form.email} onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))} type="email" autoComplete="off" /></label>
          <label className="field">角色
            <select value={form.role} onChange={(event) => setForm((current) => ({ ...current, role: event.target.value as AdminRole }))}>
              {Object.entries(adminRoleLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="field">{account ? "重置密码" : "初始密码"}<input value={form.password} onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))} type="password" autoComplete="new-password" placeholder={account ? "留空则不修改" : ""} /></label>
        </div>
        <label className="check-line">
          <input checked={form.is_active} onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))} type="checkbox" />
          {account ? "启用该管理员账号" : "创建后立即启用"}
        </label>
        {!account ? (
          <>
            <label className="check-line">
              <input checked={Boolean(form.create_openapi_key)} onChange={(event) => setForm((current) => ({ ...current, create_openapi_key: event.target.checked }))} type="checkbox" />
              同时创建 OpenAPI 用户
            </label>
            {form.create_openapi_key ? (
              <div className="form-grid">
                <label className="field wide">OpenAPI 用户名称
                  <input value={form.openapi_key_name ?? ""} onChange={(event) => setForm((current) => ({ ...current, openapi_key_name: event.target.value }))} placeholder={`${form.username || "账号"} OpenAPI`} />
                </label>
                <label className="check-line"><input type="checkbox" checked={(form.openapi_scopes ?? []).includes("openagent:upload-token")} onChange={(event) => setForm((current) => ({ ...current, openapi_scopes: event.target.checked ? Array.from(new Set([...(current.openapi_scopes ?? []), "openagent:upload-token"])) : (current.openapi_scopes ?? []).filter((scope) => scope !== "openagent:upload-token") }))} />允许获取发包上传 Token</label>
                <label className="check-line"><input type="checkbox" checked={(form.openapi_scopes ?? []).includes("openagent:release:write")} onChange={(event) => setForm((current) => ({ ...current, openapi_scopes: event.target.checked ? Array.from(new Set([...(current.openapi_scopes ?? []), "openagent:release:write"])) : (current.openapi_scopes ?? []).filter((scope) => scope !== "openagent:release:write") }))} />允许创建/更新发包版本</label>
              </div>
            ) : null}
          </>
        ) : null}
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>{createdOpenAPIKey ? "关闭" : "取消"}</button>
          {!createdOpenAPIKey ? <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中..." : account ? "保存修改" : "创建账号"}</button> : null}
        </div>
      </form>
    </div>
  );
}

function FeedbackDialog({ feedback, onClose, afterDone }: { feedback: UserFeedback; onClose: () => void; afterDone: () => void }) {
  const [status, setStatus] = useState<UserFeedbackStatus>(feedback.status);
  const [adminRemark, setAdminRemark] = useState(feedback.admin_remark ?? "");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await updateFeedback(feedback.id, status, adminRemark);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "反馈处理失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="drawer-backdrop" role="dialog" aria-modal="true">
      <form className="drawer-panel" onSubmit={submit}>
        <button className="drawer-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>处理用户反馈</h3>
        <p>{feedback.username} 于 {feedback.created_at ? formatDateTime(feedback.created_at) : "-"} 提交。</p>
        <div className="feedback-detail-box">
          <strong>反馈内容</strong>
          <p>{feedback.description}</p>
        </div>
        {feedback.image_urls.length ? (
          <div className="feedback-image-strip">
            {feedback.image_urls.map((url) => (
              <a href={url} target="_blank" rel="noreferrer" key={url}>
                <img src={url} alt="反馈截图" />
              </a>
            ))}
          </div>
        ) : null}
        <label className="field">处理状态
          <select value={status} onChange={(event) => setStatus(event.target.value as UserFeedbackStatus)}>
            {feedbackStatusOptions.filter((option) => option.value !== "all").map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="field">处理备注<textarea value={adminRemark} onChange={(event) => setAdminRemark(event.target.value)} rows={5} placeholder="记录处理结果、用户沟通情况或后续动作" /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="drawer-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中..." : "保存处理结果"}</button>
        </div>
      </form>
    </div>
  );
}

function LeadModuleDialog({ user, onClose, afterDone }: { user: ManagedUser; onClose: () => void; afterDone: () => void }) {
  const [form, setForm] = useState<UserLeadModuleInput>({
    is_enabled: true,
    enterprise_id: "",
    enterprise_account: "",
    enterprise_password: "",
  });
  const [currentModule, setCurrentModule] = useState<UserLeadModule | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let ignore = false;
    setIsLoading(true);
    getUserLeadModule(user.id)
      .then((module) => {
        if (ignore) return;
        setCurrentModule(module);
        setForm({
          is_enabled: module.is_enabled,
          enterprise_id: module.enterprise_id ?? "",
          enterprise_account: module.enterprise_account ?? "",
          enterprise_password: "",
        });
        setError("");
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "客资模块配置加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [user.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const enterpriseId = form.enterprise_id.trim();
    const enterpriseAccount = form.enterprise_account.trim();
    const enterprisePassword = form.enterprise_password?.trim() ?? "";
    if (form.is_enabled && (!enterpriseId || !enterpriseAccount)) {
      setError("开通时必须填写企业 ID 和企业账号");
      return;
    }
    if (form.is_enabled && !currentModule?.id && !enterprisePassword) {
      setError("首次开通时必须填写企业密码");
      return;
    }

    setError("");
    setIsSubmitting(true);
    try {
      const nextModule = await saveUserLeadModule(user.id, {
        is_enabled: form.is_enabled,
        enterprise_id: enterpriseId,
        enterprise_account: enterpriseAccount,
        enterprise_password: enterprisePassword || undefined,
      });
      setCurrentModule(nextModule);
      setForm({
        is_enabled: nextModule.is_enabled,
        enterprise_id: nextModule.enterprise_id ?? "",
        enterprise_account: nextModule.enterprise_account ?? "",
        enterprise_password: "",
      });
      afterDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "客资模块保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>客资模块开通</h3>
        <p>{user.username} 当前状态：{currentModule?.is_enabled ? "已开通" : "未开通"}。企业密码仅用于开通或重置，后台不做明文回显。</p>
        {isLoading ? <div className="inline-state">正在读取配置...</div> : null}
        <label className="check-line">
          <input checked={form.is_enabled} onChange={(event) => setForm((current) => ({ ...current, is_enabled: event.target.checked }))} type="checkbox" />
          为该用户开通客资模块
        </label>
        <div className="form-grid">
          <label className="field">企业 ID<input value={form.enterprise_id} onChange={(event) => setForm((current) => ({ ...current, enterprise_id: event.target.value }))} placeholder="ent_8aa3e8a2fc" autoComplete="off" /></label>
          <label className="field">企业账号<input value={form.enterprise_account} onChange={(event) => setForm((current) => ({ ...current, enterprise_account: event.target.value }))} autoComplete="off" /></label>
          <label className="field">企业密码<input value={form.enterprise_password ?? ""} onChange={(event) => setForm((current) => ({ ...current, enterprise_password: event.target.value }))} type="password" autoComplete="new-password" placeholder={currentModule?.id ? "留空则不修改" : "首次开通必填"} /></label>
        </div>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>关闭</button>
          <button className="primary-button" disabled={isLoading || isSubmitting}>{isSubmitting ? "保存中..." : "保存配置"}</button>
        </div>
      </form>
    </div>
  );
}

function PlanDialog({ plan, onClose, afterDone }: { plan?: RechargePlan; onClose: () => void; afterDone: () => void }) {
  const [form, setForm] = useState<Partial<RechargePlan>>(plan ?? { name: "", amount_cents: 9900, credit_amount: 1000, bonus_credit_amount: 0, team_seat_count: 0, team_duration_days: 0, sort_order: 50, is_recommended: false });
  const [amountYuan, setAmountYuan] = useState(() => ((plan?.amount_cents ?? 9900) / 100).toString());
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const normalizedAmountYuan = Number(amountYuan);
    const amountCents = Math.round(normalizedAmountYuan * 100);
    if (!form.name?.trim()) {
      setError("档位名称不能为空");
      return;
    }
    if (!Number.isFinite(normalizedAmountYuan) || amountCents <= 0 || !form.credit_amount || form.credit_amount <= 0) {
      setError("金额和积分必须大于 0");
      return;
    }
    if (!Number.isInteger(form.team_seat_count ?? 0) || (form.team_seat_count ?? 0) < 0 || !Number.isInteger(form.team_duration_days ?? 0) || (form.team_duration_days ?? 0) < 0) {
      setError("团队席位和有效天数必须是非负整数");
      return;
    }
    if (form.team_seat_count === 1) {
      setError("团队席位至少为 2（含所有者）");
      return;
    }
    if ((form.team_seat_count ?? 0) === 0 && (form.team_duration_days ?? 0) > 0) {
      setError("未配置团队席位时不能设置团队有效期");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      await saveRechargePlan({ ...form, amount_cents: amountCents });
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "充值档位保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>{plan ? "编辑充值档位" : "新增充值档位"}</h3>
        <div className="form-grid">
          <label className="field">名称<input value={form.name ?? ""} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label className="field">金额（元）<input min={0.01} step={0.01} type="number" value={amountYuan} onChange={(event) => setAmountYuan(event.target.value)} /></label>
          <label className="field">基础积分<input type="number" value={form.credit_amount ?? 0} onChange={(event) => setForm({ ...form, credit_amount: Number(event.target.value) })} /></label>
          <label className="field">赠送积分<input type="number" value={form.bonus_credit_amount ?? 0} onChange={(event) => setForm({ ...form, bonus_credit_amount: Number(event.target.value) })} /></label>
          <label className="field">团队席位<input min={0} type="number" value={form.team_seat_count ?? 0} onChange={(event) => setForm({ ...form, team_seat_count: Number(event.target.value) })} /></label>
          <label className="field">团队有效天数<input min={0} type="number" value={form.team_duration_days ?? 0} onChange={(event) => setForm({ ...form, team_duration_days: Number(event.target.value) })} /></label>
          <label className="field">标签<input value={form.badge ?? ""} onChange={(event) => setForm({ ...form, badge: event.target.value })} /></label>
          <label className="field">排序<input type="number" value={form.sort_order ?? 50} onChange={(event) => setForm({ ...form, sort_order: Number(event.target.value) })} /></label>
        </div>
        <p className="form-hint">团队席位为 0 表示普通积分档；有效天数为 0 表示永久权益。席位从包含所有者开始计算。</p>
        <label className="check-line"><input type="checkbox" checked={Boolean(form.is_recommended)} onChange={(event) => setForm({ ...form, is_recommended: event.target.checked })} /> 推荐档位</label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存档位"}</button>
        </div>
      </form>
    </div>
  );
}

function ModelSpecsDialog({ model, onClose, afterDone }: { model: AdminImageModel; onClose: () => void; afterDone: () => void }) {
  const isVideo = model.capability_type === "video" || model.work_type.split(",").map((item) => item.trim()).every((item) => item === "text_to_video" || item === "image_to_video");
  const [specs, setSpecs] = useState<ImageSpecs>({ resolutions: [], aspect_ratios: [], durations: [] });
  const [resolutionIds, setResolutionIds] = useState<number[]>(() => model.supported_resolutions.map((item) => item.id));
  const [aspectRatioIds, setAspectRatioIds] = useState<number[]>(() => model.supported_aspect_ratios.map((item) => item.id));
  const [durationIds, setDurationIds] = useState<number[]>(() => (model.supported_durations ?? []).map((item) => item.id));
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let ignore = false;
    getImageSpecs()
      .then((nextSpecs) => {
        if (!ignore) {
          setSpecs({
            resolutions: nextSpecs.resolutions ?? [],
            aspect_ratios: nextSpecs.aspect_ratios ?? [],
            durations: nextSpecs.durations ?? [],
          });
        }
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "图片规范接口不可用");
      });
    return () => {
      ignore = true;
    };
  }, []);

  const toggleId = (ids: number[], id: number) => (ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (isVideo) {
      if (!resolutionIds.length || !durationIds.length || !aspectRatioIds.length) {
        setError("至少选择一个分辨率、比例和时长");
        return;
      }
    } else if (!resolutionIds.length || !aspectRatioIds.length) {
      setError("至少选择一个分辨率和一个比例");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      await updateModelSpecs(
        model.id,
        resolutionIds,
        aspectRatioIds,
        isVideo ? durationIds : [],
      );
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "模型规格保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="drawer-backdrop" role="dialog" aria-modal="true">
      <form className="drawer-panel" onSubmit={submit}>
        <button className="drawer-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>配置模型规格</h3>
        <p>
          {isVideo
            ? `${model.name}：分辨率与时长用于计费矩阵；画面比例会传给视频模型（如 16:9 / 9:16）。`
            : `${model.name} 可用的分辨率和尺寸比例会同步给用户端模型选择。`}
        </p>
        <div className="form-section-title">分辨率</div>
        <div className="check-grid">
          {specs.resolutions.map((spec) => (
            <label className="check-line" key={spec.id}>
              <input type="checkbox" checked={resolutionIds.includes(spec.id)} onChange={() => setResolutionIds((ids) => toggleId(ids, spec.id))} />
              {spec.label}
            </label>
          ))}
        </div>
        <div className="form-section-title">尺寸比例</div>
        <div className="check-grid">
          {specs.aspect_ratios.map((spec) => (
            <label className="check-line" key={spec.id}>
              <input type="checkbox" checked={aspectRatioIds.includes(spec.id)} onChange={() => setAspectRatioIds((ids) => toggleId(ids, spec.id))} />
              {spec.label}
            </label>
          ))}
        </div>
        {isVideo ? (
          <>
            <div className="form-section-title">时长</div>
            <div className="check-grid">
              {specs.durations.map((spec) => (
                <label className="check-line" key={spec.id}>
                  <input type="checkbox" checked={durationIds.includes(spec.id)} onChange={() => setDurationIds((ids) => toggleId(ids, spec.id))} />
                  {spec.label}
                </label>
              ))}
            </div>
          </>
        ) : null}
        {error && <div className="form-error">{error}</div>}
        <div className="drawer-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存规格"}</button>
        </div>
      </form>
    </div>
  );
}

const priceAbilityOptions = [
  { value: "text_to_image", label: "文生图" },
  { value: "image_to_image", label: "图生图" },
  { value: "text_to_video", label: "文生视频" },
  { value: "image_to_video", label: "图生视频" },
  { value: "text", label: "文本" },
] as const;

const textPriceDefaults = {
  work_types: ["text"],
  resolutions: ["default"],
  aspect_ratios: ["default"],
  output_count: 1,
} as const;

function isTextAdminModel(model?: AdminImageModel) {
  if (!model) return false;
  if (model.capability_type === "text") return true;
  const workTypes = model.work_type.split(",").map((item) => item.trim()).filter(Boolean);
  return workTypes.length === 1 && (workTypes[0] === "text" || workTypes[0] === "text_generation");
}

function isVideoAdminModel(model?: AdminImageModel) {
  if (!model) return false;
  if (model.capability_type === "video") return true;
  const workTypes = model.work_type.split(",").map((item) => item.trim()).filter(Boolean);
  return workTypes.length > 0 && workTypes.every((item) => item === "text_to_video" || item === "image_to_video");
}

function PriceDialog({ models, onClose, afterDone }: { models: AdminImageModel[]; onClose: () => void; afterDone: () => void }) {
  const firstModel = models[0];
  const [form, setForm] = useState({ model_id: firstModel?.id ?? 0, output_count: 1, change_reason: "" });
  const [cellValues, setCellValues] = useState<PriceCellValues>({});
  const [surcharges, setSurcharges] = useState<PriceCellValues>({});
  const [initialSurcharges, setInitialSurcharges] = useState<PriceCellValues>({});
  const [quickSurcharge, setQuickSurcharge] = useState("");
  const [priceQuality, setPriceQuality] = useState<"any" | "low" | "medium" | "high">("any");
  const [initialCellValues, setInitialCellValues] = useState<PriceCellValues>({});
  const [activePrices, setActivePrices] = useState<Awaited<ReturnType<typeof getActiveModelPrices>>>([]);
  const [quickFillValue, setQuickFillValue] = useState("");
  const [error, setError] = useState("");
  const [isLoadingPrices, setIsLoadingPrices] = useState(Boolean(firstModel));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const selectedModel = models.find((model) => model.id === form.model_id);
  const selectedIsText = isTextAdminModel(selectedModel);
  const selectedIsVideo = isVideoAdminModel(selectedModel);
  const outputCount = selectedIsText || selectedIsVideo ? 1 : form.output_count;
  const workTypes = selectedModel?.work_type.split(",").map((item) => item.trim()).filter(Boolean) ?? [];
  const resolutions = selectedIsText
    ? [{ id: 0, code: textPriceDefaults.resolutions[0], label: "按次" }]
    : selectedModel?.supported_resolutions ?? [];
  const columnSpecs = selectedIsText
    ? [{ id: 0, code: textPriceDefaults.aspect_ratios[0], label: "默认" }]
    : selectedIsVideo
      ? selectedModel?.supported_durations ?? []
      : selectedModel?.supported_aspect_ratios ?? [];
  const allCellKeys = workTypes.flatMap((workType) =>
    resolutions.flatMap((resolution) => columnSpecs.map((spec) => modelPriceCellKey(workType, resolution.code, spec.code))),
  );
  const cellChanged = (key: string) => isModelPriceCellChanged(cellValues[key], initialCellValues[key]) || isModelPriceCellChanged(surcharges[key] ?? "0", initialSurcharges[key] ?? "0");
  const changedCellCount = allCellKeys.filter(cellChanged).length;

  useEffect(() => {
    if (!form.model_id) return;
    let ignore = false;
    setIsLoadingPrices(true);
    setError("");
    setActivePrices([]);
    void getActiveModelPrices(form.model_id)
      .then((prices) => {
        if (!ignore) setActivePrices(prices);
      })
      .catch((err: unknown) => {
        if (!ignore) setError(err instanceof Error ? err.message : "当前价格读取失败");
      })
      .finally(() => {
        if (!ignore) setIsLoadingPrices(false);
      });
    return () => { ignore = true; };
  }, [form.model_id]);

  useEffect(() => {
    const values = activePriceCellValues(activePrices, outputCount, priceQuality);
    setInitialCellValues(values);
    setCellValues(values);
    const fees: PriceCellValues = {};
    for (const price of activePrices) {
      const key = modelPriceCellKey(price.work_type, price.resolution, price.aspect_ratio);
      if (price.is_active && price.output_count === outputCount && (price.quality ?? "any") === priceQuality && fees[key] === undefined) fees[key] = String(price.fixed_surcharge ?? 0);
    }
    setSurcharges(fees);
    setInitialSurcharges(fees);
  }, [activePrices, outputCount, priceQuality]);

  function switchModel(modelId: number) {
    setIsLoadingPrices(true);
    setActivePrices([]);
    setInitialCellValues({});
    setCellValues({});
    setForm((current) => ({ ...current, model_id: modelId, output_count: 1 }));
    setQuickFillValue("");
    setPriceQuality("any");
  }

  function setCellValue(key: string, value: string) {
    setCellValues((current) => ({ ...current, [key]: value }));
    setError("");
  }

  function quickFill(mode: "empty" | "all") {
    const creditCost = Number(quickFillValue);
    if (!Number.isInteger(creditCost) || creditCost <= 0) {
      setError("批量积分必须是大于 0 的整数");
      return;
    }
    setCellValues((current) => {
      const next = { ...current };
      for (const key of allCellKeys) {
        if (mode === "all" || !(next[key] ?? "").trim()) next[key] = String(creditCost);
      }
      return next;
    });
    setError("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedModel || !workTypes.length || !resolutions.length || !columnSpecs.length) {
      setError("模型缺少能力或规格配置，请先完善模型规格");
      return;
    }
    if (!form.change_reason.trim()) {
      setError("价格变更必须填写原因");
      return;
    }
    const changedKeys = allCellKeys.filter(cellChanged);
    if (!changedKeys.length) {
      setError("请先修改至少一个价格");
      return;
    }
    const invalidKey = changedKeys.find((key) => {
      const creditCost = Number((cellValues[key] ?? "").trim());
      return !Number.isInteger(creditCost) || creditCost <= 0;
    });
    if (invalidKey) {
      setError("已修改的价格必须是大于 0 的整数；如需停用价格，请在价格列表操作");
      return;
    }
    if (changedKeys.some((key) => !/^\d+(\.\d{1,2})?$/.test(surcharges[key] ?? "0") || Number(surcharges[key] ?? "0") > 100000000)) {
      setError("固定加价须为非负数，最多两位小数"); return;
    }
    const priceEntries = changedModelPriceEntries(cellValues, initialCellValues, surcharges, initialSurcharges);
    setIsSubmitting(true);
    setError("");
    try {
      await createModelPricesBatch({
        model_id: form.model_id,
        work_types: workTypes,
        resolutions: resolutions.map((spec) => spec.code),
        aspect_ratios: columnSpecs.map((spec) => spec.code),
        output_count: outputCount,
        change_reason: form.change_reason.trim(),
        price_matrix: {},
        price_entries: priceEntries,
        quality: selectedIsText || selectedIsVideo ? "any" : priceQuality,
      });
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "价格保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!selectedModel) {
    return (
      <div className="drawer-backdrop" role="dialog" aria-modal="true">
        <div className="drawer-panel">
          <button className="drawer-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
          <h3>配置模型价格</h3>
          <p>请先创建模型并配置其支持的能力与规格。</p>
          <div className="drawer-actions"><button className="secondary-button" type="button" onClick={onClose}>关闭</button></div>
        </div>
      </div>
    );
  }

  return (
    <div className="drawer-backdrop" role="dialog" aria-modal="true">
      <form className="drawer-panel drawer-panel--pricing" onSubmit={submit}>
        <button className="drawer-close" type="button" disabled={isSubmitting} onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>配置模型价格</h3>
        <p>实际价格 = 基础价格 × 客户 VIP 折扣 + 固定加价。固定加价不参与折扣，每个计费规格单独配置；保存后生成新版本。</p>

        <div className="form-grid">
          <label className="field">模型<select value={form.model_id} disabled={isSubmitting} onChange={(event) => switchModel(Number(event.target.value))}>{models.map((model) => <option value={model.id} key={model.id}>{model.name}</option>)}</select></label>
          {!selectedIsText && !selectedIsVideo && <label className="field">质量<select value={priceQuality} disabled={isSubmitting || changedCellCount > 0} onChange={(event) => setPriceQuality(event.target.value as typeof priceQuality)}>
            <option value="any">通用价格</option><option value="low">低</option><option value="medium">中（含自动）</option><option value="high">高</option>
          </select><small>质量专属价格优先；未配置时使用通用价格。有未保存修改时请先保存或关闭。</small></label>}
          {!selectedIsText && !selectedIsVideo ? (
            <label className="field">输出张数<input type="number" min={1} step={1} disabled={isSubmitting} value={form.output_count} onChange={(event) => setForm((current) => ({ ...current, output_count: Math.max(1, Number(event.target.value) || 1) }))} /></label>
          ) : (
            <div className="inline-hint">{selectedIsText ? "文本模型按次计费" : "视频模型固定单条输出"}</div>
          )}
        </div>

        <div className="quick-config-bar price-quick-fill">
          <label className="field">批量基础价格<input type="number" min={1} step={1} value={quickFillValue} disabled={isLoadingPrices || isSubmitting} onChange={(event) => setQuickFillValue(event.target.value)} /></label>
          <div className="row-actions">
            <button className="secondary-button compact" type="button" disabled={isLoadingPrices || isSubmitting || !allCellKeys.length} onClick={() => quickFill("empty")}>仅填空白</button>
            <button className="secondary-button compact" type="button" disabled={isLoadingPrices || isSubmitting || !allCellKeys.length} onClick={() => quickFill("all")}>应用到全部规格</button>
          </div>
          <span>批量操作只修改草稿，点击保存后才生效。</span>
        </div>

        <div className="quick-config-bar price-quick-fill">
          <label className="field">批量固定加价<input type="number" min={0} step="0.01" value={quickSurcharge} disabled={isLoadingPrices || isSubmitting} onChange={(event) => setQuickSurcharge(event.target.value)} /></label>
          <button className="secondary-button compact" type="button" disabled={isLoadingPrices || isSubmitting} onClick={() => {
            if (!/^\d+(\.\d{1,2})?$/.test(quickSurcharge) || Number(quickSurcharge) > 100000000) { setError("固定加价须为非负数，最多两位小数"); return; }
            setSurcharges((current) => ({ ...current, ...Object.fromEntries(allCellKeys.filter((key) => cellValues[key]?.trim()).map((key) => [key, quickSurcharge])) })); setError("");
          }}>应用到已填规格</button>
          <span>每张／次固定收取，不参与 VIP 折扣。</span>
        </div>
        {isLoadingPrices ? <div className="inline-state">正在读取当前生效价格…</div> : null}
        {!isLoadingPrices && (!workTypes.length || !resolutions.length || !columnSpecs.length) ? (
          <div className="form-error">该模型缺少能力或规格，请先回到模型管理补齐。</div>
        ) : null}

        {!isLoadingPrices ? workTypes.map((workType) => {
          const ability = priceAbilityOptions.find((option) => option.value === workType);
          const abilityLabel = ability?.label ?? (workType === "text_generation" ? "文本" : workType);
          return (
            <section className="price-matrix-section" key={workType}>
              <div className="form-section-title">{abilityLabel}</div>
              <div className="price-matrix">
                <table>
                  <thead><tr><th>分辨率</th>{columnSpecs.map((spec) => <th key={spec.code}>{selectedIsVideo ? `${spec.label}时长` : spec.label}</th>)}</tr></thead>
                  <tbody>
                    {resolutions.map((resolution) => (
                      <tr key={resolution.code}>
                        <td><strong>{resolution.label}</strong><small>{resolution.code}</small></td>
                        {columnSpecs.map((spec) => {
                          const key = modelPriceCellKey(workType, resolution.code, spec.code);
                          const changed = cellChanged(key);
                          return (
                            <td key={spec.code}>
                              <label className="field">基础价格<input
                                className={changed ? "is-changed" : undefined}
                                type="number"
                                min={1}
                                step={1}
                                disabled={isSubmitting}
                                value={cellValues[key] ?? ""}
                                placeholder="未配置"
                                aria-label={`${abilityLabel} ${resolution.label} ${spec.label}积分`}
                                onChange={(event) => setCellValue(key, event.target.value)}
                              /></label>
                              <label className="field">固定加价<input type="number" min={0} step="0.01" disabled={isSubmitting} value={surcharges[key] ?? "0"} aria-label={`${abilityLabel} ${resolution.label} ${spec.label}固定加价`} onChange={(event) => setSurcharges((current) => ({ ...current, [key]: event.target.value }))} /></label>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        }) : null}

        <div className="inline-hint price-change-summary">
          <strong>{changedCellCount ? `待保存 ${changedCellCount} 项变更` : "当前没有待保存变更"}</strong>
          <span>空白表示尚未配置；清空已有价格不会停用它，请在价格列表执行停用。</span>
        </div>
        <label className="field">变更原因<textarea value={form.change_reason} disabled={isSubmitting} onChange={(event) => setForm((current) => ({ ...current, change_reason: event.target.value }))} rows={3} /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="drawer-actions">
          <button className="secondary-button" type="button" disabled={isSubmitting} onClick={onClose}>取消</button>
          <button className="primary-button" disabled={isLoadingPrices || isSubmitting || changedCellCount === 0}>{isSubmitting ? "保存中…" : `保存 ${changedCellCount || ""} 项变更`}</button>
        </div>
      </form>
    </div>
  );
}

const modelProviderPresets = {
  openai: {
    label: "OpenAI / GPT",
    provider_name: "OpenAI",
    provider_code: "openai",
    base_url: "https://api.openai.com/v1",
    access_mode: "api" as const,
  },
  gemini: {
    label: "Google Gemini / Banana",
    provider_name: "Google Gemini",
    provider_code: "gemini",
    base_url: "https://generativelanguage.googleapis.com/v1beta",
    access_mode: "api" as const,
  },
  google31sdk: {
    label: "Google 3.1 Image（SDK）",
    provider_name: "Google 3.1 Image",
    provider_code: "google-3-1-image-sdk",
    base_url: "http://127.0.0.1:8045/v1",
    access_mode: "sdk" as const,
  },
  xai: {
    label: "xAI Grok Imagine",
    provider_name: "xAI",
    provider_code: "xai",
    base_url: "http://159.195.95.114:8317/v1",
    access_mode: "api" as const,
  },
} as const;

function slugifyModelCode(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

type ModelProviderPresetKey = keyof typeof modelProviderPresets;

const imageCapabilityValues = ["text_to_image", "image_to_image"] as const;
const videoCapabilityValues = ["text_to_video", "image_to_video"] as const;

function inferModelProviderPreset(model?: AdminImageModel): ModelProviderPresetKey {
  const providerCode = (model?.provider_code ?? "").toLowerCase();
  const providerName = (model?.provider_name ?? "").toLowerCase();
  const baseUrl = (model?.base_url ?? model?.base_url_masked ?? "").toLowerCase();
  const vendorModel = (model?.vendor_model ?? "").toLowerCase();
  if (vendorModel.includes("grok-imagine") || providerCode.includes("xai") || providerName.includes("xai") || baseUrl.includes("x.ai") || baseUrl.includes("159.195.95.114")) {
    return "xai";
  }
  if ((model?.access_mode ?? "api") === "sdk" || vendorModel.includes("gemini-3.1")) {
    return "google31sdk";
  }
  if (providerCode.includes("gemini") || providerName.includes("gemini") || baseUrl.includes("generativelanguage.googleapis.com") || vendorModel.includes("gemini")) {
    return "gemini";
  }
  return "openai";
}

function modelImageCapabilities(model?: AdminImageModel): Array<"text_to_image" | "image_to_image"> {
  const capabilities = (model?.work_type ?? "text_to_image")
    .split(",")
    .map((item) => item.trim())
    .map((item) => item === "image_edit" ? "image_to_image" : item)
    .filter((item): item is "text_to_image" | "image_to_image" => imageCapabilityValues.includes(item as "text_to_image" | "image_to_image"));
  return capabilities.length ? capabilities : ["text_to_image"];
}

function modelVideoCapabilities(model?: AdminImageModel): Array<"text_to_video" | "image_to_video"> {
  const capabilities = (model?.work_type ?? "image_to_video")
    .split(",")
    .map((item) => item.trim())
    .filter((item): item is "text_to_video" | "image_to_video" => videoCapabilityValues.includes(item as "text_to_video" | "image_to_video"));
  return capabilities.length ? capabilities : ["image_to_video"];
}

function resolveCapabilityType(model?: AdminImageModel): "image" | "text" | "video" {
  if (model?.capability_type === "text") return "text";
  if (model?.capability_type === "video") return "video";
  if (model && isVideoAdminModel(model)) return "video";
  return "image";
}

function ModelDialog({ model, onClose, afterDone }: { model?: AdminImageModel; onClose: () => void; afterDone: () => void }) {
  const initialPreset = inferModelProviderPreset(model);
  const [providerPreset, setProviderPreset] = useState<ModelProviderPresetKey>(initialPreset);
  const selectedInitialPreset = modelProviderPresets[initialPreset];
  const initialCapability = resolveCapabilityType(model);
  const [form, setForm] = useState<AdminImageModelInput>({
    provider_id: model?.provider_id,
    provider_name: model?.provider_name ?? selectedInitialPreset.provider_name,
    provider_code: model?.provider_code ?? selectedInitialPreset.provider_code,
    base_url: model?.base_url ?? selectedInitialPreset.base_url,
    access_mode: model?.access_mode ?? selectedInitialPreset.access_mode,
    api_key: "",
    capability_type: initialCapability,
    image_capabilities: initialCapability === "image" ? modelImageCapabilities(model) : [],
    video_capabilities: initialCapability === "video" ? modelVideoCapabilities(model) : [],
    supported_resolution_ids: model?.supported_resolutions.map((item) => item.id) ?? [],
    supported_aspect_ratio_ids: model?.supported_aspect_ratios.map((item) => item.id) ?? [],
    supported_duration_ids: (model?.supported_durations ?? []).map((item) => item.id),
    supports_image_edit: modelImageCapabilities(model).includes("image_to_image"),
    name: model?.name ?? "",
    code: model?.code ?? "",
    vendor_model: model?.vendor_model ?? "",
    work_type: model?.work_type ?? "text_to_image",
    description: model?.description ?? "",
    is_recommended: model?.is_recommended ?? false,
    is_stable: model?.is_stable ?? true,
    is_new: model?.is_new ?? false,
    max_input_images: model?.max_input_images ?? 1,
    max_output_images: model?.max_output_images ?? 1,
    concurrency_limit: model?.concurrency_limit ?? 1,
    sort_order: model?.sort_order ?? 50,
    timeout_seconds: model?.timeout_seconds ?? null,
    disable_retry: model?.disable_retry ?? false,
    is_active: model?.is_active ?? false,
    is_public: model?.is_public ?? true,
    storage_mode: model?.storage_mode ?? "local",
  });
  const [specs, setSpecs] = useState<ImageSpecs>({ resolutions: [], aspect_ratios: [], durations: [] });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [discoveredModels, setDiscoveredModels] = useState<Array<{ id: string; name: string }>>(
    model?.vendor_model ? [{ id: model.vendor_model, name: model.vendor_model }] : [],
  );
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoverSummary, setDiscoverSummary] = useState("");
  const providerModelOptions = (() => {
    const options = discoveredModels.map((item) => ({ value: item.id, label: item.name || item.id }));
    if (form.vendor_model && !options.some((item) => item.value === form.vendor_model)) {
      options.unshift({ value: form.vendor_model, label: `${form.vendor_model}（当前配置）` });
    }
    return options;
  })();

  const applyProviderPreset = (presetKey: ModelProviderPresetKey) => {
    const preset = modelProviderPresets[presetKey];
    setProviderPreset(presetKey);
    setDiscoveredModels([]);
    setDiscoverSummary("");
    setForm((current) => ({
      ...current,
      provider_id: undefined,
      provider_name: preset.provider_name,
      provider_code: preset.provider_code,
      base_url: preset.base_url,
      access_mode: preset.access_mode,
      vendor_model: "",
      capability_type: presetKey === "xai" ? "video" : current.capability_type,
      video_capabilities: presetKey === "xai" ? (current.video_capabilities.length ? current.video_capabilities : ["text_to_video", "image_to_video"]) : current.video_capabilities,
      image_capabilities: presetKey === "xai" ? [] : current.image_capabilities,
      max_input_images: presetKey === "xai" ? Math.max(current.max_input_images || 1, 7) : current.max_input_images,
      storage_mode: presetKey === "xai" ? "native" : current.storage_mode,
    }));
  };

  async function queryProviderModels() {
    if (!form.base_url.trim()) {
      setError("请先填写 Base URL");
      return;
    }
    if (!form.api_key.trim() && !form.provider_id) {
      setError("请先填写 API Key 后再查询供应商模型");
      return;
    }
    setIsDiscovering(true);
    setError("");
    setDiscoverSummary("");
    try {
      const result = await discoverProviderModels({
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim() || undefined,
        provider_code: form.provider_code.trim() || undefined,
        provider_name: form.provider_name.trim() || undefined,
        access_mode: form.access_mode,
        provider_id: form.provider_id,
      });
      if (result.status !== "succeeded" || !result.items.length) {
        setDiscoveredModels(form.vendor_model ? [{ id: form.vendor_model, name: form.vendor_model }] : []);
        setDiscoverSummary(result.summary || "未查询到供应商模型");
        setError(result.summary || "未查询到供应商模型");
        return;
      }
      setDiscoveredModels(result.items);
      setDiscoverSummary(result.summary || `已查询到 ${result.items.length} 个模型`);
      setForm((current) => {
        const stillValid = result.items.some((item) => item.id === current.vendor_model);
        const nextVendor = stillValid ? current.vendor_model : result.items[0].id;
        const selected = result.items.find((item) => item.id === nextVendor) ?? result.items[0];
        const nextCode = current.code.trim() || slugifyModelCode(selected.id);
        const nextName = current.name.trim() || selected.name || selected.id;
        return {
          ...current,
          vendor_model: nextVendor,
          code: nextCode,
          name: nextName,
        };
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "查询供应商模型失败");
    } finally {
      setIsDiscovering(false);
    }
  }

  function onVendorModelChange(nextVendorModel: string) {
    const selected = discoveredModels.find((item) => item.id === nextVendorModel);
    setForm((current) => {
      const previousSelected = discoveredModels.find((item) => item.id === current.vendor_model);
      const previousAutoName = previousSelected?.name || previousSelected?.id || current.vendor_model;
      const previousAutoCode = slugifyModelCode(current.vendor_model);
      const shouldReplaceName = !current.name.trim() || current.name.trim() === previousAutoName;
      const shouldReplaceCode = !current.code.trim() || current.code.trim() === previousAutoCode;
      return {
        ...current,
        vendor_model: nextVendorModel,
        name: shouldReplaceName ? (selected?.name || nextVendorModel) : current.name,
        code: shouldReplaceCode ? slugifyModelCode(nextVendorModel) : current.code,
      };
    });
  }

  useEffect(() => {
    let ignore = false;
    getImageSpecs()
      .then((nextSpecs) => {
        if (ignore) return;
        const normalized: ImageSpecs = {
          resolutions: nextSpecs.resolutions ?? [],
          aspect_ratios: nextSpecs.aspect_ratios ?? [],
          durations: nextSpecs.durations ?? [],
        };
        setSpecs(normalized);
        setForm((current) => ({
          ...current,
          supported_resolution_ids: current.supported_resolution_ids.length
            ? current.supported_resolution_ids
            : normalized.resolutions.filter((spec) => spec.is_active).map((spec) => spec.id),
          supported_aspect_ratio_ids: current.supported_aspect_ratio_ids.length
            ? current.supported_aspect_ratio_ids
            : normalized.aspect_ratios.filter((spec) => spec.is_active).map((spec) => spec.id),
          supported_duration_ids: current.supported_duration_ids.length
            ? current.supported_duration_ids
            : normalized.durations.filter((spec) => spec.is_active).map((spec) => spec.id),
        }));
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "图片规范接口不可用");
      });
    return () => {
      ignore = true;
    };
  }, []);

  const toggleId = (ids: number[], id: number) => (ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]);

  function onCapabilityTypeChange(nextType: "image" | "text" | "video") {
    setForm((current) => ({
      ...current,
      capability_type: nextType,
      image_capabilities: nextType === "image" ? (current.image_capabilities.length ? current.image_capabilities : ["text_to_image"]) : [],
      video_capabilities: nextType === "video" ? (current.video_capabilities.length ? current.video_capabilities : ["text_to_video", "image_to_video"]) : [],
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.provider_name.trim() || !form.base_url.trim() || (!model && !form.api_key.trim())) {
      setError(model ? "供应商名称和 Base URL 不能为空" : "供应商名称、Base URL 和 API Key 不能为空");
      return;
    }
    if (!form.name.trim() || !form.code.trim() || !form.vendor_model.trim()) {
      setError("请先查询并选择供应商模型，并填写用户展示名称与模型编码");
      return;
    }
    if (form.capability_type === "image" && form.image_capabilities.length === 0) {
      setError("图片模型至少要勾选一个二级能力");
      return;
    }
    if (form.capability_type === "video" && form.video_capabilities.length === 0) {
      setError("视频模型至少要勾选一个二级能力");
      return;
    }
    if (form.capability_type === "image" && (!form.supported_resolution_ids.length || !form.supported_aspect_ratio_ids.length)) {
      setError("至少选择一个支持的分辨率和尺寸");
      return;
    }
    if (form.capability_type === "video" && (!form.supported_resolution_ids.length || !form.supported_duration_ids.length || !form.supported_aspect_ratio_ids.length)) {
      setError("至少选择一个支持的分辨率、比例和时长");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const workType =
        form.capability_type === "text"
          ? "text"
          : form.capability_type === "video"
            ? form.video_capabilities.join(",")
            : form.image_capabilities.join(",");
      await saveModel({
        ...form,
        name: form.name.trim(),
        code: form.code.trim(),
        provider_name: form.provider_name.trim(),
        provider_code: form.provider_code.trim() || form.provider_name.trim().toLowerCase().replace(/\s+/g, "-"),
        base_url: form.base_url.trim(),
        access_mode: form.access_mode,
        api_key: form.api_key.trim(),
        vendor_model: form.vendor_model.trim(),
        work_type: workType,
        supports_image_edit: form.capability_type === "image" && form.image_capabilities.includes("image_to_image"),
        supported_resolution_ids: form.capability_type === "text" ? [] : form.supported_resolution_ids,
        supported_aspect_ratio_ids: form.capability_type === "text" ? [] : form.supported_aspect_ratio_ids,
        supported_duration_ids: form.capability_type === "video" ? form.supported_duration_ids : [],
        max_input_images: form.capability_type === "text" ? 0 : form.max_input_images,
        max_output_images: form.capability_type === "text" ? 0 : form.capability_type === "video" ? 1 : form.max_output_images,
        description: form.description.trim(),
        is_active: false,
      }, model?.id);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "模型保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="drawer-backdrop" role="dialog" aria-modal="true">
      <form className="drawer-panel drawer-panel--wide" onSubmit={submit}>
        <button className="drawer-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>{model ? "编辑模型" : "新增模型"}</h3>
        <p>填写供应商 API 连接信息和模型能力。API Key 只用于保存或覆盖，列表只展示脱敏值。</p>
        <div className="form-section-title">API 接入</div>
        <div className="form-grid">
          <label className="field">厂商<select value={providerPreset} onChange={(event) => applyProviderPreset(event.target.value as ModelProviderPresetKey)}>
            {Object.entries(modelProviderPresets).map(([key, preset]) => <option key={key} value={key}>{preset.label}</option>)}
          </select></label>
          <label className="field">供应商名称<input value={form.provider_name} onChange={(event) => setForm({ ...form, provider_name: event.target.value })} placeholder="例如 OpenAI / xAI" /></label>
          <label className="field">供应商编码<input value={form.provider_code} onChange={(event) => setForm({ ...form, provider_code: event.target.value })} placeholder="留空按名称自动生成" /></label>
          <label className="field">Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label>
          <label className="field">接入方式<select value={form.access_mode} onChange={(event) => setForm({ ...form, access_mode: event.target.value as "api" | "sdk" })}><option value="api">API</option><option value="sdk">SDK</option></select></label>
          <label className="field">API Key<input value={form.api_key} onChange={(event) => setForm({ ...form, api_key: event.target.value })} type="password" placeholder={model ? "留空则不修改" : "保存后不明文回显"} /></label>
        </div>
        <div className="form-section-title with-actions">
          <span>模型能力</span>
          <span>
            <button type="button" className="secondary-button compact" disabled={isDiscovering} onClick={() => void queryProviderModels()}>
              {isDiscovering ? "查询中..." : "查询供应商模型"}
            </button>
          </span>
        </div>
        <div className="inline-hint">供应商模型根据上方 Base URL / API Key 实时查询；仅“模型名称”用于前台展示，可自由修改。</div>
        {discoverSummary ? <div className="inline-hint">{discoverSummary}</div> : null}
        <div className="form-grid">
          <label className="field">供应商模型<select value={form.vendor_model} onChange={(event) => onVendorModelChange(event.target.value)} disabled={!providerModelOptions.length}>
            {!providerModelOptions.length ? <option value="">请先查询供应商模型</option> : null}
            {providerModelOptions.map((item) => <option key={item.value} value={item.value}>{item.label} ({item.value})</option>)}
          </select></label>
          <label className="field">模型名称（用户展示）<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="前台展示名称，例如 Grok Imagine Video" /></label>
          <label className="field">模型编码<input value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} placeholder="唯一编码，默认按供应商模型生成" /><small>系统内部唯一标识；通常无需手改。</small></label>
          <label className="field">
            能力类型
            <select value={form.capability_type} onChange={(event) => onCapabilityTypeChange(event.target.value as "image" | "text" | "video")}>
              <option value="image">图片</option>
              <option value="video">视频</option>
              <option value="text">文本</option>
              <option value="multimodal" disabled>图文混合（暂不开放）</option>
            </select>
          </label>
          <label className="field">排序<input type="number" value={form.sort_order} onChange={(event) => setForm({ ...form, sort_order: Number(event.target.value) })} /></label>
          {form.capability_type === "image" || form.capability_type === "video" ? (
            <>
              <label className="field">最大输入图<input type="number" value={form.max_input_images} onChange={(event) => setForm({ ...form, max_input_images: Number(event.target.value) })} /></label>
              {form.capability_type === "image" ? (
                <label className="field">最大输出图<input type="number" value={form.max_output_images} onChange={(event) => setForm({ ...form, max_output_images: Number(event.target.value) })} /></label>
              ) : null}
            </>
          ) : null}
          <label className="field">并发上限<input type="number" min={0} value={form.concurrency_limit} onChange={(event) => setForm({ ...form, concurrency_limit: Math.max(0, Number(event.target.value)) })} /><small>0 表示不限制；例如 5 表示该模型最多同时运行 5 个任务。</small></label>
          <label className="field">任务超时（秒）<input type="number" min={10} max={3600} value={form.timeout_seconds ?? ""} onChange={(event) => { const v = event.target.value; setForm({ ...form, timeout_seconds: v === "" ? null : Math.max(10, Math.min(3600, Number(v))) }); }} placeholder="默认 120" /><small>该模型所有图片、视频或文本任务共用此总时限；排队后会写入任务快照。</small></label>
          <label className="check-line"><input type="checkbox" checked={form.disable_retry} onChange={(event) => setForm({ ...form, disable_retry: event.target.checked })} /> 禁用自动重试<small>开启后向支持该参数的图片上游传递 disable_retry，并且平台不会对超时任务再次调用模型。</small></label>
        </div>
        {form.capability_type === "image" ? (
          <>
            <div className="form-section-title">图片二级能力</div>
            <div className="check-grid">
              <label className="check-line"><input type="checkbox" checked={form.image_capabilities.includes("text_to_image")} onChange={(event) => setForm({ ...form, image_capabilities: event.target.checked ? [...form.image_capabilities, "text_to_image"] : form.image_capabilities.filter((item) => item !== "text_to_image") })} /> 文生图</label>
              <label className="check-line"><input type="checkbox" checked={form.image_capabilities.includes("image_to_image")} onChange={(event) => setForm({ ...form, image_capabilities: event.target.checked ? [...form.image_capabilities, "image_to_image"] : form.image_capabilities.filter((item) => item !== "image_to_image") })} /> 图生图</label>
            </div>
            <div className="form-section-title">支持分辨率</div>
            <div className="check-grid">
              {specs.resolutions.filter((spec) => spec.is_active).map((spec) => (
                <label className="check-line" key={spec.id}><input type="checkbox" checked={form.supported_resolution_ids.includes(spec.id)} onChange={() => setForm({ ...form, supported_resolution_ids: toggleId(form.supported_resolution_ids, spec.id) })} /> {spec.label}</label>
              ))}
            </div>
            <div className="form-section-title">支持尺寸</div>
            <div className="check-grid">
              {specs.aspect_ratios.filter((spec) => spec.is_active).map((spec) => (
                <label className="check-line" key={spec.id}><input type="checkbox" checked={form.supported_aspect_ratio_ids.includes(spec.id)} onChange={() => setForm({ ...form, supported_aspect_ratio_ids: toggleId(form.supported_aspect_ratio_ids, spec.id) })} /> {spec.label}</label>
              ))}
            </div>
          </>
        ) : form.capability_type === "video" ? (
          <>
            <div className="form-section-title">视频二级能力</div>
            <div className="check-grid">
              <label className="check-line"><input type="checkbox" checked={form.video_capabilities.includes("text_to_video")} onChange={(event) => setForm({ ...form, video_capabilities: event.target.checked ? [...form.video_capabilities, "text_to_video"] : form.video_capabilities.filter((item) => item !== "text_to_video") })} /> 文生视频</label>
              <label className="check-line"><input type="checkbox" checked={form.video_capabilities.includes("image_to_video")} onChange={(event) => setForm({ ...form, video_capabilities: event.target.checked ? [...form.video_capabilities, "image_to_video"] : form.video_capabilities.filter((item) => item !== "image_to_video") })} /> 图生视频</label>
            </div>
            <div className="form-section-title">支持分辨率</div>
            <div className="check-grid">
              {specs.resolutions.filter((spec) => spec.is_active).map((spec) => (
                <label className="check-line" key={spec.id}><input type="checkbox" checked={form.supported_resolution_ids.includes(spec.id)} onChange={() => setForm({ ...form, supported_resolution_ids: toggleId(form.supported_resolution_ids, spec.id) })} /> {spec.label}</label>
              ))}
            </div>
            <div className="form-section-title">支持比例</div>
            <div className="check-grid">
              {specs.aspect_ratios.filter((spec) => spec.is_active).map((spec) => (
                <label className="check-line" key={spec.id}><input type="checkbox" checked={form.supported_aspect_ratio_ids.includes(spec.id)} onChange={() => setForm({ ...form, supported_aspect_ratio_ids: toggleId(form.supported_aspect_ratio_ids, spec.id) })} /> {spec.label}</label>
              ))}
            </div>
            <div className="form-section-title">支持时长</div>
            <div className="check-grid">
              {specs.durations.filter((spec) => spec.is_active).map((spec) => (
                <label className="check-line" key={spec.id}><input type="checkbox" checked={form.supported_duration_ids.includes(spec.id)} onChange={() => setForm({ ...form, supported_duration_ids: toggleId(form.supported_duration_ids, spec.id) })} /> {spec.label}</label>
              ))}
            </div>
            <div className="inline-hint">视频按「分辨率 × 时长」计费；比例会传给上游视频模型。保存后请到价格配置填写积分并启用。</div>
          </>
        ) : (
          <div className="inline-hint">文本模型用于提示词优化等能力，无需配置分辨率和尺寸；保存后请到价格配置填写积分并启用。</div>
        )}
        <label className="field">描述<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={3} /></label>
        <label className="field">结果存储方式
          <select value={form.storage_mode ?? "local"} onChange={(event) => setForm({ ...form, storage_mode: event.target.value as "local" | "third_party" | "native" })}>
            <option value="local">本地存储（MinIO）</option>
            <option value="third_party">三方存储（七牛等）</option>
            <option value="native">原生存储（保留模型返回链接）</option>
          </select>
          <small>Grok 等直接返回媒体链接的模型建议选「原生存储」；本地 MinIO 选本地；七牛等 CDN 选三方。</small>
        </label>
        <div className="check-grid">
          <label className="check-line"><input type="checkbox" checked={form.is_recommended} onChange={(event) => setForm({ ...form, is_recommended: event.target.checked })} /> 推荐</label>
          <label className="check-line"><input type="checkbox" checked={form.is_stable} onChange={(event) => setForm({ ...form, is_stable: event.target.checked })} /> 稳定</label>
          <label className="check-line"><input type="checkbox" checked={form.is_new} onChange={(event) => setForm({ ...form, is_new: event.target.checked })} /> 新模型</label>
          <label className="check-line"><input type="checkbox" checked={form.is_public} onChange={(event) => setForm({ ...form, is_public: event.target.checked })} /> 上架给普通用户</label>
        </div>
        {error && <div className="form-error">{error}</div>}
        <div className="drawer-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中..." : model ? "保存修改" : "保存模型"}</button>
        </div>
      </form>
    </div>
  );
}

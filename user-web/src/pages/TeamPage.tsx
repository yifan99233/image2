import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Crown, Loader2, ShieldCheck, Trash2, UsersRound } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { teamService } from "@/services/team";
import type { TeamMember, TeamOption, TeamSettings } from "@/types/api";

const memberDisplayName = (member: TeamMember) => member.nickname || member.username || member.email;

const roleLabel: Record<string, string> = {
  owner: "所有者",
  admin: "管理员",
  member: "成员",
};

const workspaceLabel = (team: TeamSettings | TeamOption | null | undefined) => {
  // A personal workspace is the automatically-created workspace without a
  // team entitlement. A team can still have only its owner seated, so member
  // count must not be used to decide which wallet will be charged.
  if (team && !team.collaboration_enabled) return "个人版";
  return "团队版";
};

export function TeamSettingsPage() {
  const [settings, setSettings] = useState<TeamSettings | null>(null);
  const [teams, setTeams] = useState<TeamOption[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [teamName, setTeamName] = useState("");
  const [imageHistoryShared, setImageHistoryShared] = useState(false);
  const [newMemberIdentifier, setNewMemberIdentifier] = useState("");
  const [newMemberRole, setNewMemberRole] = useState<"admin" | "member">("member");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isAddingMember, setIsAddingMember] = useState(false);
  const [isSwitchingTeamId, setIsSwitchingTeamId] = useState<number | null>(null);
  const [updatingMembershipId, setUpdatingMembershipId] = useState<number | null>(null);
  const [memberPendingRemoval, setMemberPendingRemoval] = useState<TeamMember | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadTeamWorkspace = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const [nextSettings, nextTeams, nextMembers] = await Promise.all([
        teamService.getSettings(),
        teamService.getTeams(),
        teamService.getMembers(),
      ]);
      setSettings(nextSettings);
      setTeams(nextTeams);
      setMembers(nextMembers);
      setTeamName(nextSettings.name);
      setImageHistoryShared(nextSettings.image_history_shared);
    } catch (err) {
      setError(err instanceof Error ? err.message : "团队工作区加载失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTeamWorkspace();
  }, [loadTeamWorkspace]);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  const isOwner = settings?.current_role === "owner";
  const canManageMembers = settings?.current_role === "owner" || settings?.current_role === "admin";
  const activeTeam = useMemo(() => teams.find((team) => team.is_active) ?? settings, [settings, teams]);
  const activeWorkspaceLabel = workspaceLabel(activeTeam);
  const accessibleTeams = useMemo(() => teams.filter((team) => team.collaboration_enabled), [teams]);
  const entitlementLabel = settings?.entitlement_expires_at
    ? `有效至 ${new Date(settings.entitlement_expires_at).toLocaleDateString("zh-CN")}`
    : "永久团队权益";

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isOwner) return;
    const name = teamName.trim();
    if (!name) {
      setError("请输入团队名称");
      return;
    }
    setIsSaving(true);
    setError("");
    try {
      const nextSettings = await teamService.updateSettings({
        name,
        image_history_shared: imageHistoryShared,
      });
      setSettings(nextSettings);
      setTeamName(nextSettings.name);
      setImageHistoryShared(nextSettings.image_history_shared);
      setTeams((current) => current.map((team) => (team.id === nextSettings.id ? { ...team, ...nextSettings } : team)));
      setNotice("团队设置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "团队设置保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  const switchTeam = async (team: TeamOption) => {
    if (team.is_active || isSwitchingTeamId !== null) return;
    setIsSwitchingTeamId(team.id);
    setError("");
    try {
      await teamService.setActiveTeam(team.id);
      await loadTeamWorkspace();
      setNotice(`已切换至${workspaceLabel(team)}「${team.name}」`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "团队切换失败");
    } finally {
      setIsSwitchingTeamId(null);
    }
  };

  const addMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManageMembers || isAddingMember) return;
    const identifier = newMemberIdentifier.trim();
    if (!identifier) {
      setError("请输入成员邮箱或用户名");
      return;
    }
    setIsAddingMember(true);
    setError("");
    try {
      const member = await teamService.addMember({ identifier, role: isOwner ? newMemberRole : "member" });
      setMembers((current) => [...current, member]);
      setNewMemberIdentifier("");
      setNotice(`已添加成员「${memberDisplayName(member)}」`);
      await loadTeamWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加成员失败");
    } finally {
      setIsAddingMember(false);
    }
  };

  const updateMemberRole = async (member: TeamMember, role: "admin" | "member") => {
    if (!isOwner || updatingMembershipId !== null || member.role === role) return;
    setUpdatingMembershipId(member.membership_id);
    setError("");
    try {
      const saved = await teamService.updateMemberRole(member.membership_id, role);
      setMembers((current) => current.map((item) => (item.membership_id === saved.membership_id ? saved : item)));
      setNotice(`已更新「${memberDisplayName(saved)}」的角色`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "成员角色更新失败");
    } finally {
      setUpdatingMembershipId(null);
    }
  };

  const removeMember = async () => {
    if (!memberPendingRemoval) return;
    setUpdatingMembershipId(memberPendingRemoval.membership_id);
    setError("");
    try {
      await teamService.removeMember(memberPendingRemoval.membership_id);
      setMembers((current) => current.filter((member) => member.membership_id !== memberPendingRemoval.membership_id));
      setMemberPendingRemoval(null);
      setNotice("成员已移除；其已有的个人素材不会被删除");
      await loadTeamWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "移除成员失败");
    } finally {
      setUpdatingMembershipId(null);
    }
  };

  return (
    <main className="page-surface team-page team-workspace">
      <header className="page-header team-workspace__header">
        <div>
          <p className="team-workspace__eyebrow">计费工作区</p>
          <h1>个人版 / 团队版</h1>
          <p>默认使用团队版；切换工作区后，新的生图会从对应账户扣费。</p>
        </div>
      </header>

      {error ? <div className="list-state list-state--error">{error}</div> : null}
      {notice ? <div className="inline-notice"><CheckCircle2 size={17} /><span>{notice}</span></div> : null}

      {isLoading ? (
        <div className="empty-state"><Loader2 className="spin-icon" size={30} /><p>正在加载团队工作区</p></div>
      ) : settings?.collaboration_enabled ? (
        <>
          <section className="team-workspace__overview">
            <div className="team-workspace__identity">
              <span><UsersRound size={24} /></span>
              <div>
                <p>当前工作区 · {activeWorkspaceLabel}</p>
                <h2>{activeTeam?.name ?? settings.name}</h2>
                <small>{roleLabel[settings.current_role ?? "member"] ?? "成员"} · 已使用 {settings.seats_used} / {settings.seat_limit} 席</small>
              </div>
            </div>
            <div className="team-workspace__stats" aria-label="团队状态">
              <span><UsersRound size={15} /> 剩余 {settings.seats_available} 席</span>
              <span><ShieldCheck size={15} /> 素材库已共享</span>
              <span>{entitlementLabel}</span>
              <span className={imageHistoryShared ? "is-active" : ""}>{imageHistoryShared ? "生图历史已共享" : "生图历史仅个人"}</span>
            </div>
          </section>

          <section className="team-workspace__switcher" aria-label="切换个人版或团队版">
            <div>
              <strong>选择计费工作区</strong>
              <span>个人版扣个人账户，团队版扣团队共享账户。</span>
            </div>
            <div className="team-workspace__team-list">
              {teams.map((team) => (
                <button
                  key={team.id}
                  type="button"
                  className={team.is_active ? "is-active" : ""}
                  disabled={isSwitchingTeamId !== null}
                  onClick={() => void switchTeam(team)}
                >
                  <span>{workspaceLabel(team)} · {team.name}</span>
                  <em>{team.seats_used} / {team.seat_limit} 席 · {roleLabel[team.current_role ?? "member"] ?? "成员"}</em>
                  {isSwitchingTeamId === team.id ? <Loader2 className="spin-icon" size={15} /> : null}
                </button>
              ))}
            </div>
          </section>

          <div className="team-workspace__grid">
            <form className="team-settings-panel" onSubmit={save}>
              <div className="team-workspace__section-head">
                <div><strong>团队设置</strong><span>{isOwner ? "仅团队所有者可修改" : "由团队所有者管理"}</span></div>
                {isOwner ? <Crown size={17} /> : <ShieldCheck size={17} />}
              </div>
              <label className="team-field">
                <span>团队名称</span>
                <input value={teamName} maxLength={120} disabled={!isOwner || isSaving} onChange={(event) => setTeamName(event.target.value)} />
              </label>
              <div className="team-workspace__share-row">
                <div>
                  <strong>共享生图历史</strong>
                  <p>开启后，当前团队成员可在创作记录和作品中看到团队任务。</p>
                </div>
                <button
                  type="button"
                  className={imageHistoryShared ? "team-toggle is-on" : "team-toggle"}
                  disabled={!isOwner || isSaving}
                  aria-pressed={imageHistoryShared}
                  onClick={() => setImageHistoryShared((current) => !current)}
                >
                  <span aria-hidden />
                  {imageHistoryShared ? "已开启" : "关闭"}
                </button>
              </div>
              {isOwner ? <div className="team-actions"><Button type="submit" isLoading={isSaving}>保存设置</Button></div> : null}
            </form>

            <section className="team-members-panel" aria-label="团队成员">
              <div className="team-workspace__section-head">
                <div><strong>团队成员</strong><span>成员切换到此团队后即可参与共享创作；管理员可维护普通成员。</span></div>
                <span className="team-members-panel__count">{members.length}</span>
              </div>
              {canManageMembers ? (
                <form className="team-members-panel__add" onSubmit={addMember}>
                  <input value={newMemberIdentifier} onChange={(event) => setNewMemberIdentifier(event.target.value)} placeholder="成员邮箱或用户名" disabled={isAddingMember} />
                  {isOwner ? (
                    <select value={newMemberRole} onChange={(event) => setNewMemberRole(event.target.value as "admin" | "member")} disabled={isAddingMember}>
                      <option value="member">成员</option>
                      <option value="admin">管理员</option>
                    </select>
                  ) : <span className="team-members-panel__role-note">普通成员</span>}
                  <Button type="submit" isLoading={isAddingMember}>添加</Button>
                </form>
              ) : null}
              <div className="team-members-panel__list">
                {members.map((member) => {
                  const memberIsOwner = member.role === "owner";
                  const busy = updatingMembershipId === member.membership_id;
                  return (
                    <article key={member.membership_id}>
                      <span className="team-member-avatar">{memberDisplayName(member).slice(0, 1).toUpperCase()}</span>
                      <div>
                        <strong>{memberDisplayName(member)}</strong>
                        <span>{member.email}</span>
                      </div>
                      {isOwner && !memberIsOwner ? (
                        <select value={member.role} disabled={busy} onChange={(event) => void updateMemberRole(member, event.target.value as "admin" | "member") }>
                          <option value="admin">管理员</option>
                          <option value="member">成员</option>
                        </select>
                      ) : (
                        <em>{roleLabel[member.role] ?? member.role}</em>
                      )}
                      {canManageMembers && !memberIsOwner && (isOwner || member.role === "member") ? (
                        <button type="button" className="team-members-panel__remove" disabled={busy} onClick={() => setMemberPendingRemoval(member)} aria-label={`移除 ${memberDisplayName(member)}`}>
                          {busy ? <Loader2 className="spin-icon" size={15} /> : <Trash2 size={15} />}
                        </button>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            </section>
          </div>
        </>
      ) : settings ? (
        <section className="team-upgrade" aria-label="团队版开通说明">
          <div className="team-upgrade__icon"><UsersRound size={28} /></div>
          <div>
            <p className="team-workspace__eyebrow">团队权益</p>
            <h2>当前账号尚未开通团队版</h2>
            <p>个人创作与素材不会受影响。购买含团队席位的充值档位，或由后台直接开通后，即可邀请成员并共享团队素材与创作历史。</p>
          </div>
          {accessibleTeams.length ? (
            <div className="team-upgrade__switch">
              <strong>你已加入以下团队</strong>
              {accessibleTeams.map((team) => (
                <Button key={team.id} variant="secondary" type="button" disabled={isSwitchingTeamId !== null} onClick={() => void switchTeam(team)}>
                  {isSwitchingTeamId === team.id ? <Loader2 className="spin-icon" size={16} /> : null}
                  切换至团队版 · {team.name}
                </Button>
              ))}
            </div>
          ) : <Link className="button button--primary" to="/billing/recharge">查看团队档位</Link>}
        </section>
      ) : null}

      {memberPendingRemoval ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setMemberPendingRemoval(null)}>
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="team-remove-member-title" onClick={(event) => event.stopPropagation()}>
            <div className="dialog-icon dialog-icon--danger"><Trash2 size={22} /></div>
            <h2 id="team-remove-member-title">移除团队成员？</h2>
            <p>将“{memberDisplayName(memberPendingRemoval)}”移出当前团队。对方已有的个人素材与作品不会被删除。</p>
            <div className="dialog-actions">
              <Button variant="ghost" type="button" disabled={updatingMembershipId !== null} onClick={() => setMemberPendingRemoval(null)}>取消</Button>
              <Button variant="danger" type="button" isLoading={updatingMembershipId === memberPendingRemoval.membership_id} onClick={() => void removeMember()}>移除成员</Button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}

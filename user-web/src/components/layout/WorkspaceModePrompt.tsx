import { useEffect, useMemo, useState } from "react";
import { Building2, Check, WalletCards } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { teamService } from "@/services/team";
import { useAuthStore } from "@/stores/authStore";
import { CREDIT_BALANCE_CHANGED_EVENT } from "@/utils/creditEvents";
import type { TeamOption } from "@/types/api";

const isTeamWorkspace = (team: TeamOption) => team.collaboration_enabled;
const isTeamParticipant = (team: TeamOption, userId: number) =>
  isTeamWorkspace(team) && (team.owner_user_id !== userId || team.current_role === "owner");
const INITIALIZATION_KEY_PREFIX = "image2:workspace-mode-initialized:v1:";

const initializationKey = (userId: number) => `${INITIALIZATION_KEY_PREFIX}${userId}`;

const hasInitializedWorkspaceMode = (userId: number) => {
  try {
    return window.localStorage.getItem(initializationKey(userId)) === "1";
  } catch {
    return false;
  }
};

const markWorkspaceModeInitialized = (userId: number) => {
  try {
    window.localStorage.setItem(initializationKey(userId), "1");
  } catch {
    // A private browsing context may reject localStorage. The selection still
    // takes effect for the current session; the next load can retry the guide.
  }
};

/**
 * Ask for the billing workspace once the authenticated app shell mounts.
 * The first choice is deliberately a team workspace when one is available;
 * selecting personal remains an explicit, one-click alternative.
 */
export function WorkspaceModePrompt() {
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const [teams, setTeams] = useState<TeamOption[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const currentUserId = userId;
    if (currentUserId === null || hasInitializedWorkspaceMode(currentUserId)) {
      setIsLoading(false);
      setIsOpen(false);
      return;
    }

    let ignore = false;

    const load = async () => {
      try {
        const availableTeams = await teamService.getTeams();
        if (ignore) return;

        setTeams(availableTeams);
        const teamWorkspaces = availableTeams.filter((team) => isTeamParticipant(team, currentUserId));
        const defaultTeam = teamWorkspaces[0] ?? availableTeams.find((team) => team.is_active);
        setSelectedTeamId(defaultTeam?.id ?? null);
        // Pure personal accounts have no team version to choose from.
        setIsOpen(teamWorkspaces.length > 0);
      } catch {
        // The prompt must never block the rest of the application if the
        // optional workspace endpoint is temporarily unavailable.
        if (!ignore) setIsOpen(false);
      } finally {
        if (!ignore) setIsLoading(false);
      }
    };

    void load();
    return () => {
      ignore = true;
    };
  }, [userId]);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) ?? null,
    [selectedTeamId, teams],
  );

  const confirm = async () => {
    if (!selectedTeam || isSaving) return;
    setIsSaving(true);
    setError("");
    try {
      await teamService.setActiveTeam(selectedTeam.id);
      if (userId !== null) markWorkspaceModeInitialized(userId);
      setIsOpen(false);
      window.dispatchEvent(new CustomEvent(CREDIT_BALANCE_CHANGED_EVENT));
    } catch (err) {
      setError(err instanceof Error ? err.message : "工作区切换失败，请稍后重试");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading || !isOpen || !selectedTeam) return null;

  return (
    <div className="modal-backdrop workspace-mode-backdrop" role="presentation">
      <section
        className="workspace-mode-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workspace-mode-title"
        aria-describedby="workspace-mode-description"
      >
        <div className="workspace-mode-dialog__icon"><WalletCards size={24} /></div>
        <div className="workspace-mode-dialog__header">
          <p>开始创作前选择计费版本</p>
          <h2 id="workspace-mode-title">你要使用个人版还是团队版？</h2>
          <span id="workspace-mode-description">新的图片、视频任务会从所选版本对应的账户扣费。默认已选中团队版。</span>
        </div>

        <div className="workspace-mode-options" role="radiogroup" aria-label="选择计费版本">
          {teams.map((team) => {
            const teamMode = isTeamWorkspace(team);
            const selected = team.id === selectedTeamId;
            return (
              <button
                key={team.id}
                type="button"
                className={selected ? "workspace-mode-option is-selected" : "workspace-mode-option"}
                role="radio"
                aria-checked={selected}
                onClick={() => setSelectedTeamId(team.id)}
              >
                <span className="workspace-mode-option__icon">{teamMode ? <Building2 size={21} /> : <WalletCards size={21} />}</span>
                <span className="workspace-mode-option__body">
                  <strong>{teamMode ? "团队版" : "个人版"}</strong>
                  <small>{teamMode ? `${team.name} · 团队共享账户` : `${team.name} · 个人账户`}</small>
                </span>
                <span className="workspace-mode-option__check" aria-hidden="true">{selected ? <Check size={16} /> : null}</span>
              </button>
            );
          })}
        </div>

        {error ? <p className="workspace-mode-dialog__error">{error}</p> : null}
        <div className="workspace-mode-dialog__actions">
          <Button type="button" fullWidth isLoading={isSaving} onClick={() => void confirm()}>
            使用{isTeamWorkspace(selectedTeam) ? "团队版" : "个人版"}
          </Button>
        </div>
      </section>
    </div>
  );
}

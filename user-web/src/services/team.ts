import { request } from "@/services/http";
import type { TeamMember, TeamOption, TeamSettings } from "@/types/api";

export const teamService = {
  async getSettings(): Promise<TeamSettings> {
    return request<TeamSettings>("/team");
  },

  async updateSettings(input: Partial<Pick<TeamSettings, "name" | "image_history_shared">>): Promise<TeamSettings> {
    return request<TeamSettings>("/team", { method: "PATCH", body: input });
  },

  async getTeams(): Promise<TeamOption[]> {
    return request<TeamOption[]>("/team/teams");
  },

  async setActiveTeam(teamId: number): Promise<TeamSettings> {
    return request<TeamSettings>("/team/active", { method: "POST", body: { team_id: teamId } });
  },

  async getMembers(): Promise<TeamMember[]> {
    return request<TeamMember[]>("/team/members");
  },

  async addMember(input: { identifier: string; role: "admin" | "member" }): Promise<TeamMember> {
    return request<TeamMember>("/team/members", { method: "POST", body: input });
  },

  async updateMemberRole(membershipId: number, role: "admin" | "member"): Promise<TeamMember> {
    return request<TeamMember>(`/team/members/${membershipId}`, { method: "PATCH", body: { role } });
  },

  async removeMember(membershipId: number): Promise<void> {
    return request<void>(`/team/members/${membershipId}`, { method: "DELETE" });
  },
};

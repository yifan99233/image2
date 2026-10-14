import { request } from "@/services/http";
import type { RechargeOrder, RechargePlan } from "@/types/api";

export const rechargeService = {
  async getPlans(): Promise<RechargePlan[]> {
    return request<RechargePlan[]>("/recharge/plans");
  },

  async createOrder(planId: number): Promise<RechargeOrder> {
    return request<RechargeOrder>("/recharge/orders", {
      method: "POST",
      body: { plan_id: planId },
    });
  },

  async getOrder(orderId: number): Promise<RechargeOrder> {
    return request<RechargeOrder>(`/recharge/orders/${orderId}`);
  },
};

import { request } from "@/services/http";
import type { BenefitGrant, BenefitOrder, BenefitPackage } from "@/types/api";

export const benefitService = {
  async getPackages(): Promise<BenefitPackage[]> {
    return request<BenefitPackage[]>("/benefits/packages");
  },

  async createOrder(packageId: number): Promise<BenefitOrder> {
    return request<BenefitOrder>("/benefits/orders", {
      method: "POST",
      body: { package_id: packageId },
    });
  },

  async getOrder(orderId: number): Promise<BenefitOrder> {
    return request<BenefitOrder>(`/benefits/orders/${orderId}`);
  },

  async getGrants(): Promise<BenefitGrant[]> {
    return request<BenefitGrant[]>("/benefits/grants");
  },
};

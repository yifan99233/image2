import { request } from "@/services/http";
import type { CreditBalance, CreditLedgerItem } from "@/types/api";

export const creditService = {
  async getBalance(): Promise<CreditBalance> {
    return request<CreditBalance>("/credits/balance");
  },

  async getLedger(): Promise<CreditLedgerItem[]> {
    return request<CreditLedgerItem[]>("/credits/ledger");
  },
};

import type { ModelPrice } from "../types";

export type ModelPriceEntry = {
  work_type: string;
  resolution: string;
  aspect_ratio: string;
  credit_cost: number;
  fixed_surcharge?: number;
};

export type PriceCellValues = Record<string, string>;

export function modelPriceCellKey(workType: string, resolution: string, aspectRatio: string): string {
  return JSON.stringify([workType, resolution, aspectRatio]);
}

export function activePriceCellValues(prices: ModelPrice[], outputCount: number): PriceCellValues {
  const values: PriceCellValues = {};
  for (const price of prices) {
    if (!price.is_active || price.output_count !== outputCount) continue;
    const key = modelPriceCellKey(price.work_type, price.resolution, price.aspect_ratio);
    if (values[key] === undefined) values[key] = String(price.credit_cost);
  }
  return values;
}

export function isModelPriceCellChanged(currentValue = "", initialValue = ""): boolean {
  const current = currentValue.trim();
  const initial = initialValue.trim();
  if (current === initial) return false;
  if (!current || !initial) return true;
  const currentNumber = Number(current);
  const initialNumber = Number(initial);
  return !Number.isFinite(currentNumber) || !Number.isFinite(initialNumber) || currentNumber !== initialNumber;
}

export function changedModelPriceEntries(current: PriceCellValues, initial: PriceCellValues, surcharges?: PriceCellValues, initialSurcharges: PriceCellValues = {}): ModelPriceEntry[] {
  const entries: ModelPriceEntry[] = [];
  for (const [key, rawValue] of Object.entries(current)) {
    const value = rawValue.trim();
    if (!value || (!isModelPriceCellChanged(value, initial[key]) && !isModelPriceCellChanged(surcharges?.[key] ?? "0", initialSurcharges[key] ?? "0"))) continue;
    const creditCost = Number(value);
    if (!Number.isInteger(creditCost) || creditCost <= 0) continue;
    const parsedKey: unknown = JSON.parse(key);
    if (!Array.isArray(parsedKey) || parsedKey.length !== 3 || !parsedKey.every((part) => typeof part === "string")) continue;
    entries.push({
      work_type: parsedKey[0],
      resolution: parsedKey[1],
      aspect_ratio: parsedKey[2],
      credit_cost: creditCost,
      ...(surcharges ? { fixed_surcharge: Number(surcharges[key] ?? "0") } : {}),
    });
  }
  return entries;
}

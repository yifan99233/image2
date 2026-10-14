import assert from "node:assert/strict";
import test from "node:test";

const { activePriceCellValues, changedModelPriceEntries, isModelPriceCellChanged, modelPriceCellKey } = await import("./modelPriceMatrix.ts");

const basePrice = {
  id: 1,
  model_id: 132,
  model_name: "model",
  work_type: "text_to_image",
  resolution: "4k",
  aspect_ratio: "16:9",
  output_count: 1,
  credit_cost: 24,
  version: 2,
  effective_at: "2026-08-04T00:00:00Z",
  is_active: true,
  change_reason: "test",
};

test("maps active prices by the complete billable specification", () => {
  const values = activePriceCellValues(
    [basePrice, { ...basePrice, id: 2, output_count: 2, credit_cost: 40 }],
    1,
  );

  assert.deepEqual(values, {
    [modelPriceCellKey("text_to_image", "4k", "16:9")]: "24",
  });
});

test("submits only valid cells whose price changed", () => {
  const unchangedKey = modelPriceCellKey("text_to_image", "1k", "1:1");
  const changedKey = modelPriceCellKey("image_to_image", "4k", "16:9");
  const invalidKey = modelPriceCellKey("text_to_image", "2k", "1:1");

  assert.deepEqual(
    changedModelPriceEntries(
      { [unchangedKey]: "16", [changedKey]: "30", [invalidKey]: "0" },
      { [unchangedKey]: "16", [changedKey]: "24", [invalidKey]: "" },
    ),
    [{ work_type: "image_to_image", resolution: "4k", aspect_ratio: "16:9", credit_cost: 30 }],
  );
});

test("treats equivalent integer formatting as unchanged", () => {
  assert.equal(isModelPriceCellChanged("024", "24"), false);
  assert.equal(isModelPriceCellChanged("25", "24"), true);
  assert.equal(isModelPriceCellChanged("", "24"), true);
});

test('surcharge-only changes retain base price and allow resetting the fee to zero', () => {
  const key = modelPriceCellKey('text_to_image', '1k', '1:1');
  assert.deepEqual(changedModelPriceEntries({ [key]: '10' }, { [key]: '10' }, { [key]: '2.50' }, { [key]: '0' }), [
    { work_type: 'text_to_image', resolution: '1k', aspect_ratio: '1:1', credit_cost: 10, fixed_surcharge: 2.5 },
  ]);
  assert.equal(changedModelPriceEntries({ [key]: '10' }, { [key]: '10' }, { [key]: '0' }, { [key]: '2.5' })[0].fixed_surcharge, 0);
  assert.deepEqual(changedModelPriceEntries({ [key]: '10' }, { [key]: '10' }, { [key]: '2.50' }, { [key]: '2.5' }), []);
});

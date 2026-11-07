import type { ImageAsset } from "../types/api";
import type { BatchGroup } from "./batchGroups";

export type GroupAssetCache = WeakMap<File, Map<number, ImageAsset>>;

/** Bound uploads across the whole draft, preserving reference order on retries. */
export const uploadGroupReferences = async (
  groups: BatchGroup[],
  modelId: number,
  upload: (file: File, modelId: number) => Promise<ImageAsset>,
  cache: GroupAssetCache,
  onProgress: (completed: number, total: number) => void,
): Promise<Map<string, ImageAsset[]>> => {
  const references = groups.flatMap((group) =>
    group.images.map((image, index) => ({ group, image, index })),
  );
  const results = new Map(
    groups.map((group) => [group.id, new Array<ImageAsset>(group.images.length)]),
  );
  let cursor = 0;
  let completed = 0;
  let failure: unknown;
  const worker = async () => {
    while (!failure && cursor < references.length) {
      const { group, image, index } = references[cursor++];
      try {
        let asset = cache.get(image.file)?.get(modelId);
        if (!asset) {
          asset = await upload(image.file, modelId);
          const byModel = cache.get(image.file) ?? new Map<number, ImageAsset>();
          byModel.set(modelId, asset);
          cache.set(image.file, byModel);
        }
        results.get(group.id)![index] = asset;
        onProgress(++completed, references.length);
      } catch (error) {
        failure = error || new Error("参考图上传失败");
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(4, references.length) }, () => worker()));
  if (failure) throw failure;
  return results;
};

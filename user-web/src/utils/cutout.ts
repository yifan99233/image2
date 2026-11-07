// Keep the source RGB channels; the model supplies only coverage (alpha).
export function applyMask(source: Uint8ClampedArray, mask: Uint8ClampedArray) {
  const result = new Uint8ClampedArray(source);
  for (let i = 0; i < result.length; i += 4) {
    const coverage = (mask[i] * 0.2126 + mask[i + 1] * 0.7152 + mask[i + 2] * 0.0722) / 255;
    result[i + 3] = Math.round(source[i + 3] * coverage * mask[i + 3] / 255);
  }
  return result;
}

async function decodeImage(blob: Blob, label: string): Promise<ImageBitmap> {
  if (!blob.size) throw new Error(`${label}内容为空，请重新获取图片`);
  if (/text\/|application\/json/i.test(blob.type)) {
    throw new Error(`${label}地址返回了网页或错误信息，并非图片，请检查资源地址`);
  }
  try { return await createImageBitmap(blob); }
  catch { throw new Error(`${label}无法解码，文件可能损坏或格式不受支持`); }
}

export async function composeCutout(source: Blob, mask: Blob): Promise<Blob> {
  const original = await decodeImage(source, "原图");
  let matte: ImageBitmap | undefined;
  try {
    matte = await decodeImage(mask, "接口返回的蒙版");
    if (Math.abs(original.width / original.height / (matte.width / matte.height) - 1) > 0.025) {
      throw new Error('蒙版比例与原图不一致，为避免损伤主体，未导出结果。');
    }
    const canvas = document.createElement('canvas');
    canvas.width = original.width;
    canvas.height = original.height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
    ctx.drawImage(matte, 0, 0, canvas.width, canvas.height);
    const maskPixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let colored = 0, light = 0, dark = 0;
    for (let i = 0; i < maskPixels.data.length; i += 4) {
      const [r, g, b] = maskPixels.data.subarray(i, i + 3);
      if (Math.max(r, g, b) - Math.min(r, g, b) > 24) colored++;
      if (r > 230) light++;
      if (r < 25) dark++;
    }
    const pixels = canvas.width * canvas.height;
    if (colored / pixels > 0.02 || !light || !dark) throw new Error('接口未返回有效的黑白蒙版，请重试。');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(original, 0, 0);
    const sourcePixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
    sourcePixels.data.set(applyMask(sourcePixels.data, maskPixels.data));
    ctx.putImageData(sourcePixels, 0, 0);
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG 导出失败')), 'image/png'));
  } finally { original.close(); matte?.close(); }
}

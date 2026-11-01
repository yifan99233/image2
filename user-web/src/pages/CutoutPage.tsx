import { useEffect, useRef, useState } from 'react';
import { Scissors, Upload, Download, Check, History, ArrowRight, ImagePlus, Maximize2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { LoadingState } from '@/components/ui/LoadingState';
import { modelService } from '@/services/models';
import { uploadService } from '@/services/uploads';
import { imageTaskService } from '@/services/imageTasks';
import { fetchDownloadBlob, planDownloadTarget } from '@/utils/downloadTarget';
import { resolveAssetUrl } from '@/utils/assets';
import { composeCutout } from '@/utils/cutout';
import type { ImageModel, ImageTask } from '@/types/api';
import './CutoutPage.css';

export function CutoutPage() {
  const [models, setModels] = useState<ImageModel[]>([]);
  const [modelId, setModelId] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState('');
  const [result, setResult] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [task, setTask] = useState<ImageTask | null>(null);
  const [previewBackground, setPreviewBackground] = useState('transparent');
  const inputRef = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    modelService.getModels('image_edit').then(items => {
      if (!mounted.current) return;
      const available = items.filter(item => item.max_input_images > 0);
      setModels(available); setModelId(available[0]?.id ?? 0);
      if (!available.length) setError('暂无可用模型');
    }).catch(() => { if (mounted.current) setError('模型加载失败，请刷新页面'); });
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => { if (!file) return; const url = URL.createObjectURL(file); setSource(url); return () => URL.revokeObjectURL(url); }, [file]);
  useEffect(() => () => { if (result) URL.revokeObjectURL(result); }, [result]);

  async function restoreLatest() {
    setBusy(true); setError('');
    try {
      const tasks = await imageTaskService.getTasks({ limit: 80 });
      const previous = tasks.find(item => item.prompt.startsWith('Return ONLY a grayscale foreground segmentation alpha matte') && item.input_images.length > 0 && !['failed', 'refunded'].includes(item.status));
      if (!previous) throw new Error('未找到可恢复的抠图任务');
      const originalUrl = resolveAssetUrl(previous.input_images[0].url);
      const original = await fetchDownloadBlob(planDownloadTarget(originalUrl, location.href, location.origin));
      if (!mounted.current) return;
      setFile(new File([original], '原图.png', { type: original.type }));
      setModelId(previous.model_id); setTask(previous); setResult('');
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : '恢复失败'); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function run() {
    if (!file || !modelId || busy) return;
    setBusy(true); setError('');
    try {
      let current = task;
      if (!current) {
        const asset = await uploadService.uploadImageForModel(file, modelId);
        current = await imageTaskService.createTask({
          work_type: 'image_edit', model_id: modelId, resolution: 'auto', aspect_ratio: 'auto', quality: 'auto', output_count: 1, n: 1,
          input_image_ids: [asset.id],
          prompt: 'Return ONLY a grayscale foreground segmentation alpha matte for the uploaded image. Exact same canvas aspect ratio, framing, position, scale and silhouette as input. Entire main subject solid white (255), all background black (0), antialiased edges gray. Preserve holes, fine hair and semitransparent edges. Do not draw the subject texture, colors, shadows, labels or checkerboard. Do not redraw, move, crop, expand or alter any subject geometry. Output an opaque black and white mask, not a cutout image.',
        }, [asset]);
        if (mounted.current) setTask(current);
      }
      const deadline = Date.now() + 5 * 60_000;
      while (!['succeeded', 'failed', 'refunded'].includes(current.status)) {
        if (!mounted.current) return;
        if (Date.now() > deadline) throw new Error('任务仍在处理中，点击“继续查看”获取结果，不会重复扣费。');
        await new Promise(resolve => setTimeout(resolve, 2500));
        if (!mounted.current) return;
        current = await imageTaskService.getTask(current.id);
        setTask(current);
      }
      if (current.status !== 'succeeded') {
        setTask(null);
        throw new Error(current.failure_message || '处理失败，请重试');
      }
      try { sessionStorage.setItem('cutout-pending', JSON.stringify({task: current, name: file.name, size: file.size, modified: file.lastModified})); } catch { /* Storage may be unavailable. */ }
      const url = current.output_images[0]?.url;
      if (!url) throw new Error('任务没有返回蒙版图片');
      const mask = await fetchDownloadBlob(planDownloadTarget(resolveAssetUrl(url), location.href, location.origin));
      const png = await composeCutout(file, mask);
      if (mounted.current) setResult(URL.createObjectURL(png));
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : '处理失败，请稍后重试'); }
    finally { if (mounted.current) setBusy(false); }
  }
  function selectFile(next?: File) {
        if (!next || busy) return;
        if (!['image/png','image/jpeg','image/webp'].includes(next.type) || next.size > 10 * 1024 * 1024) { setError('请选择不超过 10 MB 的 JPG、PNG 或 WEBP 图片'); return; }
        let saved;
        try { saved = JSON.parse(sessionStorage.getItem('cutout-pending') || 'null'); } catch { saved = null; }
        const matches = saved?.name === next.name && saved?.size === next.size && saved?.modified === next.lastModified;
        setFile(next); setResult(''); setTask(matches ? saved.task : null); setError('');
        if (!matches) { try { sessionStorage.removeItem('cutout-pending'); } catch { /* Storage may be unavailable. */ } }

  }
  return <section className="cutout-page">
    <header className="cutout-heading">
      <div className="cutout-heading-copy"><span className="cutout-icon"><Scissors size={23} /></span><div><h1>抠图去背景</h1><p>留下每一处细节，让主体成为焦点。</p></div></div>
      <ol className="cutout-steps" aria-label="抠图流程">
        <li data-active={!file}><span>{file ? <Check size={12} /> : '1'}</span>上传图片</li><ArrowRight size={13} aria-hidden="true" />
        <li data-active={!!file && !result}><span>{result ? <Check size={12} /> : '2'}</span>去除背景</li><ArrowRight size={13} aria-hidden="true" />
        <li data-active={!!result}><span>3</span>下载作品</li>
      </ol>
    </header>
    <input ref={inputRef} className="cutout-file-input" aria-label="上传抠图图片" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={e => { selectFile(e.target.files?.[0]); e.target.value = ''; }} />
    <div className="cutout-workspace">
      <div className="cutout-toolbar">
        <label>处理模型<select value={modelId} disabled={busy || !!task} onChange={e => setModelId(Number(e.target.value))}>{models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
        <button className="cutout-history" onClick={restoreLatest} disabled={busy}><History size={16} />恢复上次任务</button>
        <div className="cutout-primary-actions">
          {file && <Button variant="secondary" disabled={busy} onClick={() => inputRef.current?.click()}><Upload size={16} />更换图片</Button>}
          {result ? <a className="button button--primary" href={result} download={`${file?.name.replace(/\.[^.]+$/, '')}-透明底.png`}><Download size={17} />下载透明 PNG</a>
          : <Button onClick={run} disabled={!file || !modelId} isLoading={busy}><Scissors size={17} />{busy ? '正在处理' : task ? '继续查看' : '开始抠图'}</Button>}
        </div>
      </div>
      {error && <p role="alert" className="cutout-error">{error}</p>}
      <div className="cutout-grid">
        <article>
          <h2><span><i />原始图片</span><small>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : '从一张图片开始'}</small></h2>
          <div className="cutout-preview" onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault(); selectFile(e.dataTransfer.files[0]);}}>
            {source ? <img src={source} alt="原始图片" /> : <button className="cutout-upload-zone" disabled={busy} onClick={() => inputRef.current?.click()}><span className="cutout-upload-art"><ImagePlus size={34} strokeWidth={1.4} /></span><strong>点击上传，或拖入图片</strong><span>商品、人物、创意素材，都可以从这里开始</span><em><Upload size={15} />选择图片</em><small>JPG / PNG / WEBP · 最大 10 MB</small></button>}
          </div>
          <footer><span title={file?.name}>{file?.name || '支持单张图片处理'}</span><small>原图</small></footer>
        </article>
        <article className="cutout-result-panel">
          <h2><span><i />透明底效果</span><small className={result ? 'cutout-ready' : ''}>{result ? <><Check size={13} />已完成</> : busy ? '处理中' : '等待处理'}</small></h2>
          <div className={`cutout-preview cutout-background--${previewBackground}`}>
            {busy ? <LoadingState label="正在提取主体轮廓…" /> : result ? <a href={result} target="_blank" rel="noreferrer" title="打开大图检查边缘"><img src={result} alt="透明背景抠图结果，点击查看大图" /></a> : <div className="cutout-empty"><span><Scissors size={30} strokeWidth={1.4} /></span><strong>让主体，轻盈呈现</strong><p>处理后的透明图片会出现在这里</p></div>}
          </div>
          <footer><div className="cutout-swatches" role="group" aria-label="预览背景"><span>预览底色</span>{[['transparent','透明'],['white','白色'],['dark','深色']].map(([value,label]) => <button key={value} type="button" className={`cutout-swatch cutout-background--${value}`} aria-label={`${label}预览背景`} title={`${label}预览背景`} aria-pressed={previewBackground === value} onClick={() => setPreviewBackground(value)} />)}</div>{result && <a href={result} target="_blank" rel="noreferrer"><Maximize2 size={14} />查看大图</a>}</footer>
        </article>
      </div>
      <div className="cutout-bottom-note"><span><Check size={14} />保留原图颜色与纹理</span><span>原始尺寸导出</span><span>透明 PNG · 预览底色不影响下载</span></div>
    </div>
    <details className="cutout-help"><summary>处理说明与注意事项</summary><p>仅修改透明度，AI 识别的边缘可能存在偏差，请放大检查后使用。按所选图生图模型计费，恢复任务不会重新生成。任务记录保存的是黑白蒙版，透明图片请在本页下载。</p>{task?.output_images[0]?.url && <a href={resolveAssetUrl(task.output_images[0].url)} target="_blank" rel="noreferrer">查看本次蒙版</a>}</details>
  </section>;
}

import { chromium } from 'playwright';
import assert from 'node:assert/strict';
const base = process.env.CANVAS_TEST_BASE || 'http://127.0.0.1:5179';
const browser = await chromium.launch({headless:true,channel:process.env.CANVAS_TEST_BROWSER || "chrome"});
const context = await browser.newContext({viewport:{width:1512,height:982}});
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors=[];
page.on('pageerror', e=> errors.push(e.message));
const projects=new Map();
let createdTasks=0;
let tasksComplete=false;
let statusRequests=0;
const quotes=[];
async function until(predicate, message) {
 const deadline=Date.now()+15000;
 while(!predicate()) { if(Date.now()>deadline) throw new Error(message); await new Promise(resolve=>setTimeout(resolve,100)); }
}
const imageBytes=Buffer.from(await page.evaluate(()=>{
 const canvas=document.createElement('canvas');canvas.width=960;canvas.height=640;
 const ctx=canvas.getContext('2d');ctx.fillStyle='#c7d2fe';ctx.fillRect(0,0,960,640);
 ctx.fillStyle='#4338ca';ctx.fillRect(80,80,800,480);ctx.fillStyle='white';ctx.font='48px sans-serif';ctx.fillText('Canvas 960 × 640',240,340);
 return canvas.toDataURL('image/png').split(',')[1];
}),'base64');
// Native generation providers can return a URL without dimension metadata.
const asset={id:1,url:base+'/test-image.png',local_url:base+'/test-image.png',width:null,height:null,size_bytes:imageBytes.length,mime_type:'image/png',source:'generated',sha256:'test'};
const model={id:1,name:'画布测试模型',code:'canvas-test',work_type:'text_to_image',capability_type:'image',max_input_images:4,max_output_images:4,supported_resolutions:[{value:'1024',label:'1K'},{value:'2048',label:'2K'},{value:'4096',label:'4K'}],supported_aspect_ratios:['1:1','16:9','9:16','4:3','3:4','3:2','2:3','21:9'].map(value=>({value,label:value}))};
await context.addInitScript(()=>{
 localStorage.setItem('image2:user-web:access-token','local-test-only');
 localStorage.setItem('image2:user-web:theme','light');
 localStorage.setItem('image2:workspace-mode-initialized:v1:1','1');
});
await context.route('**/*',async route=>{
 const req=route.request(), url=new URL(req.url()), path=url.pathname.replace(/^\/api/,'');
 const ok=data=>route.fulfill({json:{code:0,message:'ok',data}});
 if(path==='/test-image.png') return route.fulfill({body:imageBytes,contentType:'image/png'});
 if(path==='/auth/me') return ok({id:1,username:'canvas-test',email:'canvas@example.test',is_active:true});
 if(path==='/site/config') return route.fulfill({status:503,json:{code:503,message:'use defaults',data:null}});
 if(path==='/credits/balance') return ok({balance:100,total_recharged:100,total_consumed:0});
 if(path==='/team/teams') return ok([]);
 if(path==='/models') return ok(url.searchParams.get('work_type').includes('video') ? [{...model,id:2,name:'视频测试模型',capability_type:'video',max_output_images:1,supported_resolutions:[{value:'720p',label:'720P'},{value:'1080p',label:'1080P'}],supported_durations:[{value:'6',label:'6秒'},{value:'10',label:'10秒'}]}] : [model]);
 if(path==='/models/1/quote'||path==='/models/2/quote') {quotes.push(req.postDataJSON());return ok({credit_cost:2*req.postDataJSON().output_count});}
 if(path==='/canvas/projects' && req.method()==='GET') return ok({items:[...projects.values()].map(({document,...summary})=>summary),has_more:false});
 if(path.startsWith('/canvas/projects/')) {
   const id=path.split('/').at(-1);
   if(req.method()==='PUT') {
     const body=req.postDataJSON();const old=projects.get(id);
     assert.ok(!JSON.stringify(body.document.nodes).includes("blob:"), "Cloud document contains session-only media URLs");
     assert.equal(body.revision,old?.revision||0);
     const result={id,title:body.title,document:body.document,revision:(old?.revision||0)+1,created_at:old?.created_at||new Date().toISOString(),updated_at:new Date().toISOString()};projects.set(id,result);return ok(result);
   }
   if(req.method()==='DELETE') {projects.delete(id);return ok(null);}
   return projects.has(id)?ok(projects.get(id)):route.fulfill({status:404,json:{code:404,message:'missing',data:null}});
 }
 if(path==='/image-tasks' && req.method()==='POST') {
   const body=req.postDataJSON();assert.equal(body.model_id,2);assert.equal(body.work_type,body.input_image_urls.length?'image_to_video':'text_to_video');assert.equal(body.resolution,'1080p');assert.equal(body.aspect_ratio,'16:9');assert.equal(body.duration,'10');assert.equal(body.output_count,1);createdTasks++;
   return ok({id:createdTasks,status:'queued',output_images:[]});
 }
 if(path==='/image-tasks/statuses') { statusRequests++; return ok(req.postDataJSON().task_ids.map(id=>({id,status:tasksComplete?'succeeded':'running',output_images:tasksComplete?[{...asset,id:2,url:base+'/test-video.mp4',local_url:base+'/test-video.mp4',mime_type:'video/mp4',width:1280,height:720}]:[]}))); }
 if(path==='/materials') return ok({items:[{id:1,name:'测试素材',asset}],total:1,page:1,page_size:20});
 if(path==='/materials/assets/link') return ok([]);
 if(path==='/materials/folders') return ok([]);
 if(path==='/uploads/images/r2/presign') return route.fulfill({status:400,json:{code:400,message:'multipart test',data:null}});
 if(path==='/uploads/images') return ok({...asset,width:960,height:640,source:'upload'});
 if(path==='/works'||path==='/gallery'||path==='/image-tasks') return ok([]);
 if(url.origin!==base) return route.abort();
 return route.continue();
});
async function selectSetting(frame, label, value) {
 await frame.getByRole('combobox',{name:label,exact:true}).click();
 const target=frame.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:new RegExp(`^${value}$`)});
 // Use a real pointer click so covered or clipped options fail the regression.
 await target.click({timeout:5000});
 assert.equal(await frame.locator('.canvas-image-settings-popover').isVisible(),true,`${label} selection dismissed the settings panel`);
 await frame.locator('.ant-select-dropdown:visible').waitFor({state:'hidden'});
}
try {
 await page.goto(base+'/create/canvas');
 const frame=page.frameLocator('iframe[title="画布"]');
 await frame.getByRole('button',{name:'新建画布',exact:true}).first().click();
 await frame.getByRole('button',{name:'视频',exact:true}).click();
 await frame.locator('[contenteditable="true"]').fill('海边的日落');
 await frame.getByRole('button',{name:/720p · .* · 6s/}).click();
 await selectSetting(frame,'视频分辨率','1080P');
 await selectSetting(frame,'视频画面比例','16:9');
 await selectSetting(frame,'视频时长','10秒');
 await until(()=>quotes.some(q=>q.work_type==='text_to_video'&&q.duration==='10'&&q.resolution==='1080p'),'Video settings missing from quote');
 await frame.getByText('已保存到云端',{exact:true}).click();
 await frame.getByRole('button',{name:'生成',exact:true}).click();
 await until(()=>JSON.stringify([...projects.values()]).includes('videoTaskId'),'Video task ID not saved');
 const oldRequests=statusRequests;
 await page.reload();
 await frame.locator('article').getByRole('button').first().click();
 await until(()=>statusRequests>oldRequests,'Video task not resumed');
 tasksComplete=true;
 await until(()=>[...projects.values()].some(p=>p.document.nodes.some(n=>n.type==='video'&&n.metadata?.content===base+'/test-video.mp4')),'Video result URL not saved');
 assert.equal(createdTasks,1,'Video restoration created duplicate task');
 assert.equal(errors.length,0,errors.join('\n'));
 const appFrame=page.frames().find(f=>f.url().includes('/canvas-app/'));
 const bridgeCall=async(method,input)=>appFrame.evaluate(({method,input})=>new Promise(resolve=>{
   const id=crypto.randomUUID();
   const listener=(event)=>{if(event.data?.id===id&&event.data.type==='response'){window.removeEventListener('message',listener);resolve(event.data);}};
   window.addEventListener('message',listener);
   window.parent.postMessage({channel:'image2-canvas-v1',type:'request',id,method,input},location.origin);
 }),{method,input});
 const input={modelId:2,prompt:'参考图生成视频',resolution:'1080p',aspectRatio:'16:9',quality:'auto',count:1,duration:'10',references:[asset.url]};
 const quote=await bridgeCall('generation.quote',input);
 assert.ok(quote.result);
 assert.equal(quotes.at(-1).work_type,'image_to_video');
 const invalid=await bridgeCall('generation.create',{...input,duration:'999'});
 assert.ok(invalid.error);
 assert.equal(createdTasks,1,'Invalid spec submitted a task');
 const generated=await bridgeCall('generation.create',input);
 assert.equal(generated.result.length,1);
 assert.equal(createdTasks,2);
 // Import both media types through the actual file picker. A malformed tiny video
 // still exercises metadata error fallback without a provider request.
 const picker=frame.locator('input[type="file"][accept*="video/"]');
 assert.ok((await picker.getAttribute('accept')).includes('audio/'));
 await picker.setInputFiles([
   {name:'reference-video.mp4',mimeType:'video/mp4',buffer:Buffer.from('invalid-video-metadata')},
   {name:'reference-audio.wav',mimeType:'audio/wav',buffer:Buffer.from('invalid-audio-metadata')},
 ]);
 await until(()=>[...projects.values()].some(p=>
   p.document.nodes.some(n=>n.type==='video'&&n.title==='reference-video.mp4'&&n.metadata?.mimeType==='video/mp4') &&
   p.document.nodes.some(n=>n.type==='audio'&&n.title==='reference-audio.wav'&&n.metadata?.mimeType==='audio/wav')
 ),'Video/audio picker did not create typed reference nodes');
 assert.equal(await frame.getByRole('button',{name:'音频',exact:true}).count(),1);
 assert.equal(createdTasks,2,'Importing references must not generate a task');
 await page.reload();
 await frame.locator('article').getByRole('button').first().click();
 await frame.locator('audio[src^="blob:"]').waitFor();
 await frame.locator('video[src^="blob:"]').first().waitFor();
 assert.equal(errors.length,0,errors.join('\n'));
 console.log('PASS video/audio import, typed nodes, metadata fallback and audio entry');
 console.log('PASS reference-image video routing and invalid duration rejection');
 console.log('PASS video models, dynamic settings, quote, task creation, reload recovery, persistent URL');
} catch (error) { console.log(await page.frameLocator('iframe[title="画布"]').locator("body").innerText()); throw error; } finally { await browser.close(); }

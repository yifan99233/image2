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
const submitted=[];
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
 if(path==='/models' && url.searchParams.get('work_type')==='text_to_video') return ok([]);
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
   const body=req.postDataJSON();submitted.push(body);assert.equal(body.model_id,2);assert.equal(body.work_type,body.input_image_urls.length?'image_to_video':'text_to_video');assert.equal(body.resolution,'1080p');assert.equal(body.aspect_ratio,'16:9');assert.equal(body.duration,'10');assert.equal(body.output_count,1);createdTasks++;
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

const document={nodes:[
 {id:'reference-image',type:'image',title:'草莓参考图',position:{x:-360,y:60},width:260,height:220,metadata:{content:asset.url,mimeType:'image/png',naturalWidth:960,naturalHeight:640,status:'success'}},
 {id:'video-target',type:'video',title:'视频目标',position:{x:180,y:60},width:360,height:240,metadata:{prompt:'草莓缓慢旋转',model:'image2::2',vquality:'1080p',size:'16:9',seconds:'10'}}
],connections:[],viewport:{x:350,y:130,k:0.6}};
projects.set('reference-flow',{id:'reference-flow',title:'参考图视频测试',revision:1,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),document});
try {
 await page.goto(base+'/create/canvas');
 const frame=page.frameLocator('iframe[title="画布"]');
 await frame.locator('article').getByRole('button').first().click();
 const video=frame.locator('[data-node-id="video-target"]').first();
 await video.click();
 const panelBox=await frame.locator('[data-node-prompt-panel]').boundingBox();
 assert.ok(panelBox.width>550,'Prompt controls should stay readable at 60% zoom');
 await frame.getByRole('button',{name:'添加参考',exact:true}).click();
 const hint=frame.locator('[data-reference-picker-hint]');
 await hint.waitFor();
 const box=await hint.boundingBox();
 assert.ok(box.width>400 && box.height<120,`Reference hint collapsed: ${JSON.stringify(box)}`);
 await page.screenshot({path:'/tmp/canvas-reference-picker-fixed.png'});
 await frame.locator('[data-node-id="reference-image"]').first().click();
 await hint.waitFor({state:'hidden'});
 await frame.locator('[contenteditable="true"]').waitFor();
 await until(()=>projects.get('reference-flow').document.connections.some(c=>c.fromNodeId==='reference-image'&&c.toNodeId==='video-target'),'Reference selection did not connect image to video');
 // Re-select through the sidebar too, then verify Escape and the visible back button.
 await frame.getByRole('button',{name:'断开参考连接',exact:true}).click();
 await frame.getByRole('button',{name:'添加参考',exact:true}).click();
 await frame.getByText('草莓参考图',{exact:true}).first().click();
 await hint.waitFor({state:'hidden'});
 await frame.getByRole('button',{name:'添加参考',exact:true}).click();
 await frame.getByRole('button',{name:'返回输入框',exact:true}).click();
 await hint.waitFor({state:'hidden'});
 await frame.getByRole('button',{name:'添加参考',exact:true}).click();
 await page.keyboard.press('Escape');
 await hint.waitFor({state:'hidden'});
 await frame.getByRole('button',{name:/1080p · 16:9 · 10s/}).click();
 await until(()=>quotes.some(q=>q.work_type==='image_to_video'),'Reference-only model quote did not use image_to_video');
 await frame.getByText('预计 2 积分',{exact:true}).waitFor();
 await frame.getByText('已保存到云端',{exact:true}).click();
 await page.screenshot({path:'/tmp/canvas-reference-video-ready.png'});
 await frame.getByRole('button',{name:'生成',exact:true}).click();
 await until(()=>submitted.length===1,'Image-to-video UI did not submit');
 assert.equal(submitted[0].work_type,'image_to_video');
 assert.deepEqual(submitted[0].input_image_urls,[asset.url]);
 assert.equal(submitted[0].model_id,2);
 assert.equal(submitted[0].duration,'10');
 assert.equal(errors.length,0,errors.join('\n'));
 console.log('PASS 60% zoom hint, canvas/sidebar image selection, automatic prompt return, cancel/Escape, reference-only quote and exact image-to-video payload');
} finally { await browser.close(); }

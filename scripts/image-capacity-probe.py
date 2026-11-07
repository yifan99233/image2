"""Isolated capacity probe: requires a dedicated *_test database; no provider calls."""
import asyncio,json,resource,threading,time,logging
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import text
from app.api.routes import catalog
from app.db.session import AsyncSessionLocal,engine
from app.core.config import settings
from urllib.parse import urlparse
from app.services.image_generation import GeneratedImage,GenerationModelConfig
logging.disable(logging.CRITICAL)
COUNT=5000;BYTES=2*1024*1024
assert "test" in urlparse(settings.database_url).path.rsplit("/",1)[-1], "Dedicated test database required"
assert settings.image_task_generation_max_inflight == COUNT
assert settings.image_task_callback_timeout_seconds >= 60
async def main():
 async with engine.begin() as c:
  await c.execute(text('CREATE TABLE image_tasks(id bigint PRIMARY KEY,status text,deadline_at timestamptz,worker_started_at timestamptz,worker_heartbeat_at timestamptz,provider_request_id text,provider_request_snapshot text,provider_response_summary text,provider_http_status integer)'))
  await c.execute(text("INSERT INTO image_tasks(id,status) SELECT n,'running' FROM generate_series(1,5000) n"))
 barriers={x:threading.Barrier(COUNT,timeout=90) for x in ['generation','storage']}
 mutex=threading.Lock();active=dict(generation=0,storage=0);peaks=active.copy();callback_times=[];e2e=[];failures=[]
 def generate(*args,**kw):
  begin=time.monotonic();kw['on_model_started']()
  with mutex:
   callback_times.append(time.monotonic()-begin);active['generation']+=1;peaks['generation']=max(peaks['generation'],active['generation'])
  barriers['generation'].wait()
  image=GeneratedImage(content=b'x'*BYTES,mime_type='image/png',provider_http_status=200)
  begin=time.monotonic();kw['on_model_completed'](image)
  with mutex:
   callback_times.append(time.monotonic()-begin);active['generation']-=1
  return image
 def store(**kw):
  assert len(kw['content'])==BYTES
  with mutex:active['storage']+=1;peaks['storage']=max(peaks['storage'],active['storage'])
  barriers['storage'].wait()
  with mutex:active['storage']-=1
  return {'bytes':BYTES}
 catalog.generate_image=generate;catalog.store_generated_image_object=store
 catalog.image_generation_inflight=asyncio.Semaphore(COUNT)
 config=GenerationModelConfig('probe','probe','https://unused.invalid','api','unused','bearer',300,'probe')
 started=time.monotonic();cpu=resource.getrusage(resource.RUSAGE_SELF)
 generation=ThreadPoolExecutor(COUNT);storage=ThreadPoolExecutor(COUNT)
 catalog.image_generation_executor=generation;catalog.image_storage_executor=storage
 async def execute(i):
  begin=time.monotonic()
  try:
   im,_=await catalog.run_image_generation_in_executor(config,'probe',None,'1k','1:1',task_id=i)
   await catalog.run_generated_image_storage_in_executor(user_id=1,content=im.content,mime_type=im.mime_type)
   e2e.append(time.monotonic()-begin)
  except Exception as e:
   failures.append(type(e).__name__+': '+str(e)[:100])
   for b in barriers.values():b.abort()
 async def progress():
  while True:
   await asyncio.sleep(10)
   print(json.dumps({'progress_s':round(time.monotonic()-started,1),'active':active,'peaks':peaks,'success':len(e2e),'failed':len(failures),'rss_kb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}),flush=True)
 monitor=asyncio.create_task(progress())
 try:await asyncio.wait_for(asyncio.gather(*(execute(i) for i in range(1,COUNT+1))),180)
 finally:
  monitor.cancel()
  for b in barriers.values():b.abort()
  generation.shutdown(wait=True,cancel_futures=True);storage.shutdown(wait=True,cancel_futures=True)
 async with AsyncSessionLocal() as db:
  persisted=await db.scalar(text('SELECT count(*) FROM image_tasks WHERE deadline_at IS NOT NULL AND provider_http_status=200'))
 usage=resource.getrusage(resource.RUSAGE_SELF)
 def percentile(vals,p):return round(sorted(vals)[min(len(vals)-1,int(len(vals)*p))],3) if vals else None
 print(json.dumps({'concurrency':COUNT,'success':len(e2e),'failed':len(failures),'failure_examples':list(dict.fromkeys(failures))[:5],'persisted':persisted,'bytes_per_result':BYTES,'elapsed_s':round(time.monotonic()-started,3),'p95_s':percentile(e2e,.95),'p99_s':percentile(e2e,.99),'callback_p99_s':percentile(callback_times,.99),'cpu_seconds':round(usage.ru_utime+usage.ru_stime-cpu.ru_utime-cpu.ru_stime,3),'peak_rss_kb':usage.ru_maxrss,'peaks':peaks}),flush=True)
 await engine.dispose()
 assert len(e2e)==COUNT and not failures and persisted==COUNT and peaks=={'generation':COUNT,'storage':COUNT}
asyncio.run(main())

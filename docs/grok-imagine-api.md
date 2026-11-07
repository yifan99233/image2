# Grok Imagine 接口文档（图片 / 视频）

> 版本：2026-07-15  
> 适用模型：`grok-imagine-image` / `grok-imagine-image-quality` / `grok-imagine-video` / `grok-imagine-video-1.5-preview`  
> 网关：OpenAI / xAI 兼容（本项目上游示例：`https://cpa.shyfai.cn`）  
> 说明：本文描述**标准调用约定**（路径、参数、返回、轮询），便于第三方或内部服务稳定接入。

---

## 0. 快速结论

| 能力 | 模型 | 方法 | 路径 | 是否异步 |
| --- | --- | --- | --- | --- |
| 文生图 | `grok-imagine-image` / `grok-imagine-image-quality` | `POST` | `/v1/images/generations` | 同步返回结果 |
| 图生图 / 多图编辑 | 同上 | `POST` | `/v1/images/edits` | 同步返回结果 |
| 文生视频 | `grok-imagine-video` / `grok-imagine-video-1.5-preview` | `POST` | `/v1/videos/generations` | **异步任务**，需轮询 |
| 图生视频（可多参考图） | 同上 | `POST` | `/v1/videos/generations` | **异步任务**，需轮询 |
| 查询视频任务 | — | `GET` | `/v1/videos/{request_id}` | 轮询状态 |

**重要差异**

1. **图片**：OpenAI Images 兼容；尺寸用 `size=宽x高`，不要把 `resolution` / `aspect_ratio` 原样丢给上游。  
2. **视频**：xAI Videos 兼容；用 `resolution`（如 `720p`）+ `aspect_ratio` + `duration`（秒，整数 1–15）。  
3. **视频是异步**：创建响应通常只有 `request_id`（或 `id`），结果必须通过 `GET /v1/videos/{id}` 轮询拿到。  
4. **多图**：  
   - 图片编辑：`multipart` 多文件字段 `image[]`，或 JSON 数组。  
   - 视频：首张 → `image`，其余 → `reference_images`。

---

## 1. 接入信息

### 1.1 Base URL

```text
https://cpa.shyfai.cn
```

完整前缀：

```text
https://cpa.shyfai.cn/v1
```

### 1.2 鉴权

```http
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

兼容写法（视网关配置）：

```http
x-api-key: <API_KEY>
```

### 1.3 模型清单（vendor_model）

| 模型 ID（vendor_model） | 类型 | 能力 | 说明 |
| --- | --- | --- | --- |
| `grok-imagine-image` | 图片 | 文生图、图生图 | 标准画质 |
| `grok-imagine-image-quality` | 图片 | 文生图、图生图 | 更高画质 |
| `grok-imagine-video` | 视频 | 文生视频、图生视频 | 正式视频模型 |
| `grok-imagine-video-1.5-preview` | 视频 | 图生视频（可扩展文生） | 预览版，以网关开通为准 |

> 产品侧 `model_id` 与站点绑定，**对接上游时一律传 `vendor_model` 字符串**。

---

## 2. 图片接口（文生图 / 图生图）

Grok 图片走 **OpenAI Images API** 形态，禁止落到 `/v1/responses`。

### 2.1 尺寸约定（必读）

产品 UI 可展示：

- 分辨率档位：`1k` / `2k` / `4k`
- 比例：`1:1` / `4:3` / `3:4` / `16:9` / `9:16` / `3:2` / `2:3` / `21:9`

**调用上游时必须映射成 `size`：**

```text
"{width}x{height}"
```

#### 白名单（推荐原样使用）

##### 1k

| 比例 | size |
| --- | --- |
| 1:1 | `1024x1024` |
| 4:3 | `1152x864` |
| 3:4 | `864x1152` |
| 16:9 | `1536x864` |
| 9:16 | `864x1536` |
| 3:2 | `1536x1024` |
| 2:3 | `1024x1536` |
| 21:9 | `1792x768` |

##### 2k

| 比例 | size |
| --- | --- |
| 1:1 | `2048x2048` |
| 4:3 | `2048x1536` |
| 3:4 | `1536x2048` |
| 16:9 | `2048x1152` |
| 9:16 | `1152x2048` |
| 3:2 | `2016x1344` |
| 2:3 | `1344x2016` |
| 21:9 | `2016x864` |

##### 4k

| 比例 | size |
| --- | --- |
| 1:1 | `3840x3840` |
| 4:3 | `3840x2880` |
| 3:4 | `2880x3840` |
| 16:9 | `3840x2160` |
| 9:16 | `2160x3840` |
| 3:2 | `3840x2560` |
| 2:3 | `2560x3840` |
| 21:9 | `3696x1584` |

> 这些尺寸已经按公开比例精确配对；不要让用户自由输入任意像素。

---

### 2.2 文生图

#### 接口

```http
POST /v1/images/generations
Content-Type: application/json
Authorization: Bearer <API_KEY>
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 是 | `grok-imagine-image` 或 `grok-imagine-image-quality` |
| `prompt` | string | 是 | 文本提示词 |
| `size` | string | 强烈建议 | 白名单 `宽x高`，见 §2.1 |
| `n` | number | 否 | 建议固定 `1` |
| `response_format` | string | 否 | `url`（推荐）或 `b64_json` |
| `quality` | string | 否 | 兼容字段，如 `auto` / `high`（以网关支持为准） |
| `user` | string | 否 | 终端用户标识，便于审计与限流 |

#### 请求示例

```json
{
  "model": "grok-imagine-image",
  "prompt": "赛博朋克雨夜街头，霓虹倒影，电影级构图",
  "n": 1,
  "size": "1536x864",
  "response_format": "url",
  "user": "19"
}
```

#### curl

```bash
curl "https://cpa.shyfai.cn/v1/images/generations" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-image-quality",
    "prompt": "A glass robot holding a red umbrella, studio product render",
    "n": 1,
    "size": "1024x1024",
    "response_format": "url"
  }'
```

#### 成功响应（示例）

```json
{
  "created": 1720000000,
  "data": [
    {
      "url": "https://example.com/result.png"
    }
  ]
}
```

或：

```json
{
  "created": 1720000000,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
```

---

### 2.3 图生图 / 多图编辑

#### 接口

```http
POST /v1/images/edits
```

支持两种内容类型：

1. `multipart/form-data`（文件上传，OpenAI 常见写法，**推荐多图**）  
2. `application/json`（URL / data URL / base64）

#### 参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 是 | 同上 |
| `prompt` | string | 是 | 编辑/改图指令 |
| `image` / `image[]` | file / string / array | 是 | 参考图；多图见下 |
| `size` | string | 强烈建议 | 白名单 `宽x高` |
| `n` | number/string | 否 | 建议 `1`（multipart 常为字符串） |
| `mask` | file | 否 | 蒙版，局部编辑时使用 |
| `response_format` | string | 否 | `url` / `b64_json` |
| `user` | string | 否 | 用户标识 |

#### 多图规则

| 场景 | 推荐传法 |
| --- | --- |
| 单图 | `image=@a.png` 或 JSON `"image": "https://..."` |
| 多图 | multipart 字段名 **`image[]`**，多份文件；或 JSON 数组 |

**multipart 多图示例**

```bash
curl "https://cpa.shyfai.cn/v1/images/edits" \
  -H "Authorization: Bearer $API_KEY" \
  -F "model=grok-imagine-image" \
  -F "prompt=把两张图融合成同一场景，保留人物面部" \
  -F "n=1" \
  -F "size=1024x1024" \
  -F "response_format=url" \
  -F "image[]=@ref1.png;type=image/png" \
  -F "image[]=@ref2.png;type=image/png"
```

**JSON + URL（单图）**

```json
{
  "model": "grok-imagine-image",
  "prompt": "改成日系清新色调，保留构图",
  "image": "https://cdn.example.com/source.jpg",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

**JSON + 多图 URL**

```json
{
  "model": "grok-imagine-image-quality",
  "prompt": "以第一张为主体，第二张为风格参考",
  "image": [
    "https://cdn.example.com/a.jpg",
    "https://cdn.example.com/b.jpg"
  ],
  "n": 1,
  "size": "1536x864",
  "response_format": "url"
}
```

**JSON 兼容扩展（部分网关）**

```json
{
  "model": "grok-imagine-image",
  "prompt": "增强细节",
  "image": { "url": "https://cdn.example.com/source.jpg" },
  "size": "1024x1024",
  "response_format": "url"
}
```

#### 图片接入提示

1. **不要**把 `resolution=1k`、`aspect_ratio=16:9` 直接传给 `/v1/images/*`；先映射 `size`。  
2. 多图编辑优先 `multipart` + `image[]`，兼容性最好。  
3. 输入图需公网可访问 URL 或 data URL；不要传本地相对路径。  
4. `n` 建议固定 1；批量请业务层并发多次调用。  
5. 超时建议 ≥ 60s（高画质/4k 更长）。

---

## 3. 视频接口（文生视频 / 图生视频）

### 3.1 创建视频

#### 接口

```http
POST /v1/videos/generations
Content-Type: application/json
Authorization: Bearer <API_KEY>
```

兼容备选路径（网关差异时）：

- `/v1/videos`
- `/v1/video/generations`
- `/v1/video/create`

**官方优先路径：`/v1/videos/generations`。**

#### 参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 是 | `grok-imagine-video` 或 `grok-imagine-video-1.5-preview` |
| `prompt` | string | 是 | 视频镜头/运动描述 |
| `duration` | integer | 强烈建议 | **秒数，整数 1–15**（官方字段） |
| `resolution` | string | 强烈建议 | **`480p` / `720p`**（官方字段，不是 `1k/2k`） |
| `aspect_ratio` | string | 建议 | 如 `16:9` / `9:16` / `1:1` / `3:2` / `2:3` |
| `image` | object/string | 图生视频必填 | 主参考图，见 §3.2 |
| `reference_images` | array | 否 | 额外参考图（多图模式） |
| `user` | string | 否 | 终端用户标识 |
| `seconds` | string | 否 | **兼容字段**；与 `duration` **互斥，不要同时传** |

#### 参数约束

| 字段 | 允许值 | 备注 |
| --- | --- | --- |
| `duration` | `1`–`15` | 产品常用：`6` / `10` |
| `resolution` | `480p` / `720p` | 也可传像素映射：`1280x720`→`720p`，`1920x1080`→`1080p`（是否开通 1080p 以网关为准） |
| `aspect_ratio` | `1:1` / `16:9` / `9:16` / `3:2` / `2:3` | 不要把时长塞进这个字段 |

#### 官方推荐 Body（文生视频）

```json
{
  "model": "grok-imagine-video",
  "prompt": "镜头缓慢推进，雨夜霓虹倒影，电影感运镜",
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "duration": 10,
  "user": "19"
}
```

#### 官方推荐 Body（图生视频 · 单图）

```json
{
  "model": "grok-imagine-video",
  "prompt": "根据参考图生成这个特效场景镜头",
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "duration": 10,
  "image": {
    "url": "https://cdn.example.com/ref.jpg"
  },
  "user": "19"
}
```

#### 官方推荐 Body（图生视频 · 多图）

```json
{
  "model": "grok-imagine-video",
  "prompt": "以第一张为主画面，第二张补充角色动作细节",
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "duration": 6,
  "image": {
    "url": "https://cdn.example.com/main.jpg"
  },
  "reference_images": [
    { "url": "https://cdn.example.com/ref2.jpg" },
    { "url": "https://cdn.example.com/ref3.jpg" }
  ],
  "user": "19"
}
```

#### 兼容 Body（部分网关）

```json
{
  "model": "grok-imagine-video",
  "prompt": "镜头环绕主体旋转",
  "aspect_ratio": "9:16",
  "resolution": "480p",
  "seconds": "6",
  "image": "https://cdn.example.com/ref.jpg"
}
```

> 规则：**`duration` 与 `seconds` 二选一**，不要同时出现。

#### curl

```bash
curl "https://cpa.shyfai.cn/v1/videos/generations" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video",
    "prompt": "根据参考图生成这个特效场景镜头",
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "duration": 10,
    "image": {"url": "https://cdn.example.com/ref.jpg"},
    "user": "19"
  }'
```

#### 创建响应（异步，示例）

网关可能返回以下任一形态（以实际响应为准）：

```json
{
  "request_id": "f500df15-c992-9657-a6ca-6670dc095907",
  "status": "queued"
}
```

或：

```json
{
  "id": "f500df15-c992-9657-a6ca-6670dc095907",
  "status": "processing"
}
```

**接入要求：创建成功后必须立刻持久化 `request_id`/`id`，用于轮询与故障恢复。**

---

### 3.2 多图视频规则（必须处理）

| 角色 | 字段 | 说明 |
| --- | --- | --- |
| 主参考图 | `image` | 第 1 张；对象 `{ "url": "..." }` 优先 |
| 附加参考图 | `reference_images` | 第 2 张及以后；数组 `[{ "url": "..." }]` |
| 兼容单图 | `image` 直接传 URL 字符串 | 部分网关可用 |

**错误示例（不要这样）**

```json
{
  "image": [
    "https://a.jpg",
    "https://b.jpg"
  ]
}
```

应改为：

```json
{
  "image": { "url": "https://a.jpg" },
  "reference_images": [
    { "url": "https://b.jpg" }
  ]
}
```

---

### 3.3 轮询视频任务（标准）

#### 接口

```http
GET /v1/videos/{request_id}
Authorization: Bearer <API_KEY>
```

兼容备选：

- `GET /v1/videos/generations/{request_id}`
- `GET {create_endpoint}/{request_id}`

#### 轮询建议

| 项 | 建议值 |
| --- | --- |
| 首次间隔 | 2–3s |
| 稳定间隔 | 3–5s |
| 总超时 | 300–600s |
| 状态字段 | `status` / `state`（如有） |
| 成功信号 | 出现可下载视频 URL，或 status=`succeeded`/`completed` |
| 失败信号 | status=`failed`/`error`，或错误消息 |

#### 成功响应示例（形态可能因网关略有差异）

```json
{
  "id": "f500df15-c992-9657-a6ca-6670dc095907",
  "status": "succeeded",
  "video": {
    "url": "https://vidgen.x.ai/xai-vidgen-bucket/xai-video-xxxx.mp4"
  }
}
```

或扁平字段：

```json
{
  "request_id": "f500df15-c992-9657-a6ca-6670dc095907",
  "status": "completed",
  "url": "https://vidgen.x.ai/.../xxx.mp4"
}
```

#### 结果字段识别顺序（推荐）

按优先级取第一个非空 URL：

1. `video_url`  
2. `url`  
3. `output_url` / `result_url` / `file_url` / `download_url` / `media_url`  
4. 嵌套对象：`video` / `data` / `output` / `outputs` / `results` / `videos`

#### 轮询伪代码

```python
import time, requests

def create_and_wait(api_key, body, timeout=600):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post("https://cpa.shyfai.cn/v1/videos/generations", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    job_id = data.get("request_id") or data.get("id") or data.get("task_id")
    if not job_id:
        # 少数情况下同步直接返回 url
        url = data.get("url") or (data.get("video") or {}).get("url")
        if url:
            return url
        raise RuntimeError(f"missing job id: {data}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        p = requests.get(f"https://cpa.shyfai.cn/v1/videos/{job_id}", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        p.raise_for_status()
        payload = p.json()
        status = str(payload.get("status") or payload.get("state") or "").lower()
        url = (
            payload.get("video_url")
            or payload.get("url")
            or (payload.get("video") or {}).get("url")
            or (payload.get("data") or {}).get("url")
        )
        if url:
            return url
        if status in {"failed", "error", "canceled", "cancelled"}:
            raise RuntimeError(payload)
        time.sleep(3)
    raise TimeoutError(job_id)
```

#### 视频接入提示

1. **必须存 job id**：进程重启后靠 `GET /v1/videos/{id}` 续查，禁止只靠内存轮询。  
2. 创建超时与下载超时分开：创建/轮询 300–600s；下载视频单独 60–180s。  
3. 下载结果失败时，可先落**上游视频 URL** 作为结果，避免任务卡死。  
4. `duration` 传 **number**，不要传 `"10s"` 给官方字段。  
5. 视频分辨率用 `480p/720p`，不要用图片的 `1k/2k/4k`。  
6. 多图必须 `image` + `reference_images`，不是图片 edits 的 `image[]` 语义。

---

## 4. 错误处理

### 4.1 常见 HTTP 状态

| HTTP | 含义 | 建议 |
| --- | --- | --- |
| 400 | 参数错误 | 检查 model/size/duration/image |
| 401/403 | 鉴权失败 | 检查 API Key / 模型开通 |
| 404 | 任务不存在 | job id 错误或已过期 |
| 429 | 限流 | 指数退避重试 |
| 500/502/503 | 上游异常 | 可重试；视频优先用已有 job id 续查 |

### 4.2 业务错误示例

```json
{
  "error": {
    "message": "视频时长需在 1–15 秒之间",
    "type": "invalid_request_error"
  }
}
```

### 4.3 重试策略

| 场景 | 策略 |
| --- | --- |
| 创建请求网络超时 | 可重试创建（注意幂等与重复扣费） |
| 已拿到 `request_id` | **禁止重新创建**，只轮询/续查 |
| 429 | 退避 2s → 4s → 8s… |
| 下载视频 SSL/超时 | 重试下载；仍失败则保留上游 URL |

---

## 5. 产品层映射（image2 业务侧，可选）

若对接的是本产品 `user-server`，而不是直接打 CPA：

### 5.1 创建任务

```http
POST /api/image-tasks
Authorization: Bearer <用户登录 Token>
Content-Type: application/json
```

#### 图片任务

```json
{
  "model_id": 41,
  "work_type": "text_to_image",
  "prompt": "赛博朋克雨夜",
  "resolution": "1k",
  "aspect_ratio": "16:9"
}
```

图生图：

```json
{
  "model_id": 41,
  "work_type": "image_to_image",
  "prompt": "改成日系清新色调",
  "resolution": "1k",
  "aspect_ratio": "1:1",
  "input_image_urls": [
    "https://cdn.example.com/a.jpg",
    "https://cdn.example.com/b.jpg"
  ]
}
```

#### 视频任务

```json
{
  "model_id": 43,
  "work_type": "image_to_video",
  "prompt": "根据参考图生成这个特效场景镜头",
  "resolution": "720p",
  "aspect_ratio": "16:9",
  "duration": "10",
  "input_image_urls": [
    "https://cdn.example.com/ref.jpg"
  ]
}
```

> 产品内部会把视频 `aspect_ratio + duration` 打包存为 `16:9|10`，并在执行时拆开映射到上游 `aspect_ratio` + `duration`。

### 5.2 查询任务

```http
GET /api/image-tasks/{id}
```

关注字段：

| 字段 | 说明 |
| --- | --- |
| `status` | `queued` / `running` / `succeeded` / `failed` |
| `provider_request_id` | 上游视频 job id（续查关键） |
| `output_image_url` | 成功后的图片/视频 URL |
| `failure_message` | 失败原因 |
| `credit_cost` | 积分消耗 |

---

## 6. 参数对照总表

### 6.1 图片

| 产品字段 | 上游字段 | 示例 |
| --- | --- | --- |
| `vendor_model` | `model` | `grok-imagine-image` |
| `prompt` | `prompt` | 文本 |
| `resolution` + `aspect_ratio` | `size` | `1k`+`16:9` → `1536x864` |
| 输入图列表 | `image` / `image[]` | URL 或文件 |
| 用户 ID | `user` | `"19"` |

### 6.2 视频

| 产品字段 | 上游字段 | 示例 |
| --- | --- | --- |
| `vendor_model` | `model` | `grok-imagine-video` |
| `prompt` | `prompt` | 文本 |
| `resolution` | `resolution` | `720p` |
| `aspect_ratio` | `aspect_ratio` | `16:9` |
| `duration` | `duration` | `10`（整数秒） |
| 第 1 张输入图 | `image.url` | HTTPS URL / data URL |
| 第 2+ 张输入图 | `reference_images[].url` | 数组 |
| 用户 ID | `user` | `"19"` |
| 任务 ID | 轮询路径 | `/v1/videos/{request_id}` |

---

## 7. 最小可运行清单（Checklist）

### 图片

- [ ] `Authorization: Bearer ...`
- [ ] `model` 使用 `grok-imagine-image*`
- [ ] 文生图走 `/v1/images/generations`
- [ ] 图生图走 `/v1/images/edits`
- [ ] `size` 来自白名单，不传裸 `resolution`
- [ ] 多图用 `image[]` 或 JSON 数组

### 视频

- [ ] `model` 使用 `grok-imagine-video*`
- [ ] 创建走 `POST /v1/videos/generations`
- [ ] `duration` 为 1–15 整数，且不与 `seconds` 同传
- [ ] `resolution` 为 `480p/720p`
- [ ] 多图：`image` + `reference_images`
- [ ] 持久化 `request_id`
- [ ] `GET /v1/videos/{id}` 轮询直到 URL 或失败
- [ ] 总超时 ≥ 300s

---

## 8. 附录：完整示例集合

### A. 文生图 1k 1:1

```bash
curl "https://cpa.shyfai.cn/v1/images/generations" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-image",
    "prompt": "一只玻璃质感小机器人",
    "n": 1,
    "size": "1024x1024",
    "response_format": "url"
  }'
```

### B. 图生图 多图

```bash
curl "https://cpa.shyfai.cn/v1/images/edits" \
  -H "Authorization: Bearer $API_KEY" \
  -F "model=grok-imagine-image-quality" \
  -F "prompt=融合两张参考图，电影级光影" \
  -F "n=1" \
  -F "size=2048x1152" \
  -F "response_format=url" \
  -F "image[]=@a.png;type=image/png" \
  -F "image[]=@b.png;type=image/png"
```

### C. 文生视频 10s 720p

```bash
curl "https://cpa.shyfai.cn/v1/videos/generations" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video",
    "prompt": "航拍海岸线，金色日落，缓慢推进",
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "duration": 10
  }'
```

### D. 图生视频 + 轮询

```bash
# 1) 创建
RESP=$(curl -s "https://cpa.shyfai.cn/v1/videos/generations" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video",
    "prompt": "根据参考图生成特效场景镜头",
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "duration": 10,
    "image": {"url": "https://cdn.example.com/ref.jpg"}
  }')
echo "$RESP"
JOB=$(python -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("request_id") or d.get("id") or "")' "$RESP")

# 2) 轮询
curl -s "https://cpa.shyfai.cn/v1/videos/$JOB" \
  -H "Authorization: Bearer $API_KEY"
```

---

## 9. 变更记录

| 日期 | 说明 |
| --- | --- |
| 2026-07-15 | 初版：覆盖 Grok 图片/视频标准参数、多图、视频异步轮询与产品层映射 |

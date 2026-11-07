# 文生图 / 图生图接口文档（含 1k / 2k / 4k）

> 文档版本：2026-07-13  
> 覆盖两层：
> 1. **生图网关层** `image-pipeline-api` → `4k-image-api`（OpenAI 兼容 `/v1/images/*`）
> 2. **业务产品层** `image2/user-server`（`resolution=1k|2k|4k` + `aspect_ratio` 任务接口）  
>
> 相关源码：
> - 网关：`/Users/apple/work/ppx/image-pipeline-api/4k-image-api/`
> - 产品：`/Users/apple/work/image2/user-server/app/services/image_generation.py`
> - 超分细节补充：`image-pipeline-api/docs/super-resolution-api.md`

---

## 0. 先看结论

| 问题 | 答案 |
| --- | --- |
| 文生图接口是哪个？ | `POST /v1/images/generations` |
| 图生图接口是哪个？ | `POST /v1/images/edits` |
| 业务侧 1k/2k/4k 是什么？ | 产品分辨率档位，**不是**上游直接识别的枚举 |
| 1k/2k/4k 怎么进上游？ | 产品层把 `resolution + aspect_ratio` **映射成 `size=宽x高`**，再调 OpenAI 兼容接口 |
| 4k 是原生出图吗？ | **通常不是**。上游先按可生成尺寸出图，再由 `size-adapter` **后处理放大**到目标 `size` |
| 有没有单独「只超分」接口？ | **没有**。超分绑定在 provider 的 processor 上，生图/图生图完成后自动跑 |

---

## 1. 全链路怎么走（端到端）

```text
[用户/前端]
  resolution = 1k | 2k | 4k
  aspect_ratio = 1:1 | 16:9 | ...
  prompt / input_image_url(s)
        │
        ▼
[image2 user-server]
  1) 查模型配置 / 计价
  2) _openai_size(resolution, aspect_ratio) → "2048x1152" 这类 size
  3) 有原图 → POST {base_url}/v1/images/edits  (multipart image + prompt + size)
     无原图 → POST {base_url}/v1/images/generations (JSON prompt + size)
        │
        ▼
[4k-image-api / agent3 网关]
  1) 鉴权 Authorization: Bearer <key>
  2) 解析请求（JSON / multipart）
  3) 图生图：toImageAsset(image)
       base64/dataURL → bytes
       http(s) URL     → 服务端下载 → bytes
       multipart file  → bytes
  4) provider.processor.processInput
       若 size 超过 maxWidth/maxHeight/maxPixels
       → 等比缩小 size 给上游（adaptedSize）
       → 记住原始 target 尺寸
  5) 调 chatgpt2api / 上游模型真正出图
  6) processor.processOutput
       若结果宽高都 ≥ target → 直接返回
       否则 → 超分/放大到 target（默认本地 Lanczos3）
  7) 上传对象存储，返回 data[0].url
        │
        ▼
[image2]
  落库 / 转存 CDN / 扣费完成
```

### 当前 compose 默认关键配置（网关）

```json
{
  "processors": [
    {
      "id": "resize-local-4k",
      "type": "size-adapter:local:sharp-lanczos3",
      "maxWidth": 1920,
      "maxHeight": 1920,
      "maxPixels": 2073600
    }
  ],
  "providers": [
    {
      "id": "chatgpt2api-main",
      "type": "chatgpt2api",
      "models": ["gpt-image-2", "codex-gpt-image-2", "auto", "gpt-5", "gpt-5-mini"],
      "processor": "resize-local-4k",
      "timeoutMs": 600000
    }
  ]
}
```

含义：

- 上游生图请求 `size` 会被压在约 **1920 边长 / 约 2.07M 像素** 内
- 客户端请求的更大 `size`（例如 2k、4k 映射出的尺寸）由 **后处理放大** 补齐
- `maxPixels=2073600` ≈ `1920×1080`

> 注意：`gpt-5` / `gpt-5-mini` 可能被注册在 provider models 列表里，但**图片编辑请用图片模型**（如 `gpt-image-2`），不要用对话模型。

---

## 2. 服务入口与鉴权

| 环境 | Base URL | 说明 |
| --- | --- | --- |
| 本地 compose | `http://localhost:4000` | `image-pipeline-api` 映射 `4000→3000` |
| 容器内 | `http://image-api:3000` | 同网络访问 |
| 生产/中转示例 | `https://agent3.shyfai.cn/v1` | 上游网关，语义兼容 OpenAI Images |

鉴权（网关）：

```http
Authorization: Bearer <IMAGE_API_KEY>
```

或：

```http
x-api-key: <IMAGE_API_KEY>
```

产品层 `image2` 另有自己的用户登录态 / 任务接口鉴权，不在本文 OpenAI 兼容段展开。

---

## 3. 接口总览（网关 OpenAI 兼容）

| 方法 | 路径 | action | 场景 | 可能触发超分 |
| --- | --- | --- | --- | --- |
| `POST` | `/v1/images/generations` | `generate` | **文生图** | 是 |
| `POST` | `/v1/images/edits` | `edit` | **图生图 / 图像编辑** | 是 |
| `POST` | `/v1/images/variations` | `variation` | 变体（视 provider） | 视配置 |
| `POST` | `/v1/responses` | `generate`/`edit` | Responses 风格 tool | 是 |
| `GET` | `/v1/models` | - | 已注册模型 | 否 |

下文只详细写 **文生图** 与 **图生图**。

---

## 4. 文生图：`POST /v1/images/generations`

### 4.1 基本信息

| 项 | 值 |
| --- | --- |
| Content-Type | `application/json` |
| 统一 action | `generate` |
| 下游（默认） | `chatgpt2api` → `POST /v1/images/generations`，强制 `response_format=b64_json` 拉回再存 |

### 4.2 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 建议必填 | 例如 `gpt-image-2`。未传时网关默认可能是 `test-image`（测试 provider） |
| `prompt` | string | 是 | 文本提示词 |
| `size` | string | 否 | 目标输出尺寸，格式 `宽x高`，如 `1024x1024`、`2048x2048`、`3840x2160` |
| `n` | number | 否 | 生成数量，默认按上游语义（通常 1） |
| `quality` | string | 否 | 透传上游，如 `auto` / `high` / `hd`（取决于上游支持） |
| `response_format` | string | 否 | `url`（默认路径会上传拿 URL）或 `b64_json` |
| `output_format` / `format` | string | 否 | 输出编码偏好（若上游/后处理支持） |
| `background` | string | 否 | 背景相关参数（透传/兼容） |
| `stream` | boolean | 否 | 是否流式（若启用） |
| `user` | string | 否 | 终端用户标识（透传 options） |

> **网关本身不认识 `1k`/`2k`/`4k` 字符串。**  
> 你要么直接传 `size`，要么在产品层先映射成 `size`。

### 4.3 请求示例

#### 1k 文生图（直接调网关）

```bash
curl -sS "http://localhost:4000/v1/images/generations" \
  -H "Authorization: Bearer $IMAGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只玻璃质感的小机器人撑红伞，白底产品渲染",
    "size": "1024x1024",
    "n": 1,
    "response_format": "url"
  }'
```

#### 2k 文生图

```bash
curl -sS "http://localhost:4000/v1/images/generations" \
  -H "Authorization: Bearer $IMAGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "城市夜景广角，霓虹倒影",
    "size": "2048x1152",
    "n": 1,
    "response_format": "url"
  }'
```

#### 4k 文生图

```bash
curl -sS "http://localhost:4000/v1/images/generations" \
  -H "Authorization: Bearer $IMAGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "超清山脉日出航拍",
    "size": "3840x2160",
    "n": 1,
    "response_format": "url"
  }'
```

### 4.4 成功响应（OpenAI 兼容）

```json
{
  "created": 1720000000,
  "data": [
    {
      "url": "https://.../image-outputs/images/2026/07/13/xxxx.png",
      "revised_prompt": "..."
    }
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "request_id": "..."
}
```

若走 `b64_json`，则 `data[0].b64_json` 为图片 base64。

### 4.5 文生图内部步骤（网关）

1. `parseImageGenerationRequest` 解析 `prompt/model/size/...`
2. `providerManager.invoke`
3. `processor.processInput`：必要时缩小 `size`
4. `chatgpt2api.requestImageGeneration`：JSON POST，字段含 `prompt, model, n, size, quality, response_format=b64_json`
5. 下载/解码上游图 → bytes
6. `processor.processOutput`：必要时放大到原始 `size`
7. 上传存储 → 返回 URL

---

## 5. 图生图：`POST /v1/images/edits`

### 5.1 基本信息

| 项 | 值 |
| --- | --- |
| Content-Type | `application/json` **或** `multipart/form-data` |
| 统一 action | `edit` |
| 下游（默认） | `chatgpt2api` → `POST /v1/images/edits`（**multipart** 上传 image 文件） |

### 5.2 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 建议必填 | 如 `gpt-image-2` |
| `prompt` | string | 是 | 编辑/重绘说明 |
| `image` | file / string / object / array | 是 | 原图（见下节） |
| `mask` | file / string / object | 否 | 蒙版图，透明区域可编辑 |
| `size` | string | 否 | 目标输出尺寸 `宽x高` |
| `n` | number | 否 | 数量 |
| `quality` | string | 否 | 透传 |
| `response_format` | string | 否 | `url` / `b64_json` |
| `input_fidelity` | any | 否 | 进 options（兼容扩展） |

### 5.3 `image` 输入形态（重要）

`4k-image-api` 通过 `toImageAsset` 统一解析：

| 形态 | 示例 | 处理 |
| --- | --- | --- |
| multipart 文件 | `-F image=@a.png` | 直接读 bytes |
| 纯 base64 | `"image":"iVBORw0KGgo..."` | 解码为 bytes |
| data URL | `"image":"data:image/png;base64,..."` | 解码为 bytes |
| **http(s) 链接** | `"image":"https://cdn.../a.png"` | **服务端下载 → bytes**，再向下传 |
| 对象包装 | `{"url":"..."}` / `{"image_url":"..."}` / `{"image_url":{"url":"..."}}` | 提取引用后同上 |
| 数组多图 | `["https://...","base64..."]` | 逐项解析 |

**字符串解析顺序：**

1. 是否 base64 / data URL  
2. 是否 `http(s)` 图片链接 → 下载  
3. 都不是 → **400 `invalid_image`**

链接下载失败条件（任一）：

- 非 2xx
- 超时（默认 30s）
- 空内容
- 超过大小上限（默认 **50MB**）

→ 直接 **400**，`code=invalid_image`

> 下游 chatgpt2api 始终收到 **文件 bytes（multipart）**，不会把原始 CDN 链接原样转交上游。  
> 所以：**链接是加速客户端上传的方式**，服务端仍要下载一次。

#### 关于 `images[].image_url` 双字段

- **本地 4k-image-api**：主要认 `image` 字段，不依赖 `images`。
- 某些外部网关（如历史 agent3 行为）可能同时要求：
  - `image`
  - `images: [{ "image_url": "..." }]`
- 若你发现只传其中一个 400，可临时 **dual payload**（注意 base64 时 body 会翻倍）。

### 5.4 请求示例

#### A. multipart 本地文件图生图（1k）

```bash
curl -sS "http://localhost:4000/v1/images/edits" \
  -H "Authorization: Bearer $IMAGE_API_KEY" \
  -F "model=gpt-image-2" \
  -F "prompt=轻微增强细节，保持构图" \
  -F "size=1024x1024" \
  -F "response_format=url" \
  -F "image=@./input.png;type=image/png"
```

#### B. JSON 传 CDN 链接图生图（2k，推荐本机带宽友好）

```bash
curl -sS "http://localhost:4000/v1/images/edits" \
  -H "Authorization: Bearer $IMAGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "轻微增强细节，保持构图",
    "image": "https://openagent-cdn.shyfai.cn/image2-assets/generated/19/32bdcec4bcc74cde86e247dcecebcc9c.png",
    "size": "2048x2048",
    "n": 1,
    "response_format": "url"
  }'
```

#### C. JSON base64 图生图（4k）

```bash
# 仅示意；真实 base64 很长
curl -sS "http://localhost:4000/v1/images/edits" \
  -H "Authorization: Bearer $IMAGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "提升清晰度，保留主体",
    "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
    "size": "3840x2160",
    "n": 1,
    "response_format": "url"
  }'
```

### 5.5 图生图内部步骤（网关）

1. `parseImageEditRequest`：解析 `prompt/model/image/mask/size`
2. `toImageAsset(image)`：统一变成 `{data:bytes, mimeType}`
3. `processor.processInput`：必要时缩小发给上游的 `size`
4. `chatgpt2api.requestImageEdit`：
   - FormData：`prompt/model/n/size/quality/response_format=b64_json`
   - `image` 以 **Blob 文件** append
5. 解码上游图
6. `processor.processOutput`：必要时放大
7. 上传存储 → 返回 URL

### 5.6 常见错误

| HTTP | code | 场景 |
| --- | --- | --- |
| 400 | `invalid_image` | 无图 / 非 base64 / 链接不可下载 / 空图 |
| 400 | `model_required` | 未提供 model 且无法默认 |
| 404 | `model_not_found` | 模型未注册或 action 不支持 |
| 401/403 | - | key 无效 |
| 上游超时/限流 | 映射后的 client error | chatgpt2api/上游失败 |

---

## 6. 1k / 2k / 4k 到底怎么走

### 6.1 两层语义不要混

| 层 | 字段 | 认识什么 |
| --- | --- | --- |
| 产品层 image2 | `resolution` + `aspect_ratio` | `1k` / `2k` / `4k` / `720p` 等档位 |
| 网关层 4k-image-api | `size` | 只认 `"宽x高"` 字符串，如 `2048x1152` |
| 超分层 processor | `size` + max* | 是否缩输入、是否放大输出 |

### 6.2 产品层映射表（`image2` → `size`）

源码：`user-server/app/services/image_generation.py` → `_openai_size()`

尺寸表中的宽高会保持与公开比例精确一致；不要再对宽高分别取整，否则会产生网关不支持的比例（例如 `1152x896` 实际是 `9:7`）。

#### `resolution=1k`（短边/基准约 1024）

| aspect_ratio | size |
| --- | --- |
| `1:1` | `1024x1024` |
| `4:3` | `1152x864` |
| `3:4` | `864x1152` |
| `16:9` | `1536x864` |
| `9:16` | `864x1536` |
| `3:2` | `1536x1024` |
| `2:3` | `1024x1536` |
| `21:9` | `1792x768` |

#### `resolution=2k`（基准约 2048）

| aspect_ratio | size |
| --- | --- |
| `1:1` | `2048x2048` |
| `4:3` | `2048x1536` |
| `3:4` | `1536x2048` |
| `16:9` | `2048x1152` |
| `9:16` | `1152x2048` |
| `3:2` | `2016x1344` |
| `2:3` | `1344x2016` |
| `21:9` | `2016x864` |

#### `resolution=4k`（产品表用 3840 档，不是严格 4096 方图）

| aspect_ratio | size |
| --- | --- |
| `1:1` | `3840x3840` |
| `4:3` | `3840x2880` |
| `3:4` | `2880x3840` |
| `16:9` | `3840x2160` |
| `9:16` | `2160x3840` |
| `3:2` | `3840x2560` |
| `2:3` | `2560x3840` |
| `21:9` | `3696x1584` |

另外还有 `720p` 档（产品可选）。

> 说明：`_resolution_pixels("4k")` 在另一处逻辑里是 `4096`（用于 chat-completions 的 width/height），  
> 但 **OpenAI Images 路径**走的是上面这张 `_openai_size` 表（4k 用 3840 体系）。

### 6.3 产品层选接口

`generate_image()` 逻辑摘要：

```text
if 模型走 OpenAI Images API:
  size = _openai_size(resolution, aspect_ratio)
  if 有输入图:
      multipart POST /v1/images/edits
      fields: model, prompt, n=1, size
      files: image / image[]
  else:
      JSON POST /v1/images/generations
      body: model, prompt, n=1, size
```

同时会把分辨率/比例写进 prompt 约束文案（例如「分辨率：2k，画面比例：16:9」），增强模型遵从性。

### 6.4 网关 size-adapter：1k/2k/4k 实际差在哪

以默认 `maxWidth=1920, maxHeight=1920, maxPixels=2073600`：

| 档位示例请求 size | 是否超过 max | 发给上游的 size | 后处理 |
| --- | --- | --- | --- |
| 1k `1024x1024` | 否 | **原样** `1024x1024` | 若上游结果已 ≥ target，**不放大** |
| 1k `1536x864` | 否（且像素 < 2.07M） | 原样 | 通常不放大 |
| 2k `2048x2048` | 是 | 等比缩进 max 内（约到 1920 边） | 放大回 ~2048 目标 |
| 2k `2048x1152` | 是（宽超 1920） | 缩到 max 内 | 放大回 2048x1152 |
| 4k `3840x2160` | 是 | 先缩到 max 内再生成 | 放大到 3840x2160 |
| 4k `3840x3840` | 是 | 更大幅度缩小后生成 | 放大到 3840x3840 |

#### processInput（生成前）

```text
requested = parse(size)
if requested 完全适合 maxWidth/maxHeight/maxPixels:
    不改 size
else:
    adapted = 等比 fitWithin(requested, max)
    把 input.size 改成 adapted
    在 options.sizeAdapter 记住:
      originalSize / adaptedSize / target(原始宽高)
```

#### processOutput（生成后，本地 Lanczos3）

```text
target = sizeAdapter.target 或 当前 input.size
读实际图宽高
if 实际宽 >= target.w 且 实际高 >= target.h:
    直接返回（不做超分）
else:
    按比例放大（不裁剪、不拉伸），kernel=lanczos3
    使宽、高都达到 target
```

### 6.5 一句话记住

- **1k**：多数情况 **上游直接出目标尺寸**，后处理通常 no-op  
- **2k**：多数情况 **上游先出较小图 + 后处理放大到 2k size**  
- **4k**：几乎总是 **上游小图 + 后处理放大到 4k size**  
- 产品 `resolution` 只是映射入口；真正驱动链路的是 **`size=WxH`**

---

## 7. 产品层任务接口（image2，业务侧）

> 这是 C 端/工作台使用的异步任务接口，不是 OpenAI 原生路径。

### 7.1 创建图片任务（概念字段）

常见 payload：

```json
{
  "model_id": 123,
  "work_type": "image_edit",
  "prompt": "把背景换成海边",
  "resolution": "2k",
  "aspect_ratio": "16:9",
  "input_image_url": "https://.../source.png",
  "input_image_urls": ["https://.../a.png", "https://.../b.png"]
}
```

| 字段 | 说明 |
| --- | --- |
| `model_id` | 业务模型 ID（映射 vendor_model / base_url / key） |
| `prompt` | 提示词 |
| `resolution` | `1k` / `2k` / `4k` / `720p` ... |
| `aspect_ratio` | `1:1` / `16:9` / ... |
| `input_image_url` | 单图输入（图生图） |
| `input_image_urls` | 多图输入 |
| 无输入图 | 走文生图 |

任务状态机（简）：`queued → running → succeeded/failed`，结果写 `output_image_url`。

### 7.2 产品层如何区分文生/图生

| 条件 | 走法 |
| --- | --- |
| 无 `input_image*` | 文生图 → `/v1/images/generations` |
| 有输入图 URL/内容 | 图生图 → `/v1/images/edits`（multipart 文件） |

产品层当前图生图上传方式是 **把输入图下载/读入后以文件 multipart 上传**，不是直接把 CDN 链接塞给网关（网关虽已支持链接，但产品代码路径仍以文件为主）。

---

## 8. 性能与传图建议（结合实测）

本机对 agent3 `gpt-image-2` 图生图 10 并发对照（dual payload 场景）：

| 模式 | 平均耗时 | 整批 wall | 本机上传 |
| --- | --- | --- | --- |
| CDN URL | ~61s | ~75s | ~348B |
| Base64 dual | ~158s | ~350s | 平均 ~63MB |

建议：

1. **能传链接就传链接**（省客户端上行）  
2. 大图避免 dual base64（`image` + `images[].image_url` 各一份会翻倍）  
3. 4k 比 1k 多后处理放大时间，且上游排队时尾延迟更明显  
4. 服务端下载链接也有成本，但通常仍优于客户端上传几十 MB base64

---

## 9. 错误体格式（OpenAI 风格）

```json
{
  "error": {
    "message": "Image must be a multipart file, base64 string, or http(s) image URL.",
    "type": "invalid_request_error",
    "param": "image",
    "code": "invalid_image"
  }
}
```

---

## 10. 快速对照清单

### 文生图最小可用

```http
POST /v1/images/generations
Authorization: Bearer <key>
Content-Type: application/json

{
  "model": "gpt-image-2",
  "prompt": "一只猫",
  "size": "1024x1024"
}
```

### 图生图最小可用（链接）

```http
POST /v1/images/edits
Authorization: Bearer <key>
Content-Type: application/json

{
  "model": "gpt-image-2",
  "prompt": "增强细节",
  "image": "https://example.com/a.png",
  "size": "2048x2048"
}
```

### 产品 1k/2k/4k 最小概念

```json
{
  "prompt": "增强细节",
  "resolution": "2k",
  "aspect_ratio": "1:1",
  "input_image_url": "https://example.com/a.png"
}
```

→ 产品内部变成 `size=2048x2048` 调图生图。

---

## 11. 源码索引

| 主题 | 路径 |
| --- | --- |
| 文生图路由 | `4k-image-api/server/routes/v1/images/generations.post.ts` |
| 图生图路由 | `4k-image-api/server/routes/v1/images/edits.post.ts` |
| 文生图解析 | `server/utils/openai-image/parsers/generations.ts` |
| 图生图解析 | `server/utils/openai-image/parsers/edits.ts` |
| image 链接/base64 | `server/utils/openai-image/assets.ts` |
| provider 调度 + processor | `server/utils/image/provider-manager.ts` |
| size 适配核心 | `server/utils/image/processors/size-adapter.ts` |
| 本地放大 | `server/utils/image/processors/size-adapter-local-sharp-lanczos3.ts` |
| chatgpt2api 转发 | `server/utils/image/providers/chatgpt2api.ts` |
| compose 默认配置 | `image-pipeline-api/docker-compose.yml` → `image-api` |
| 产品 1k/2k/4k 映射 | `image2/user-server/app/services/image_generation.py` |
| 产品任务创建 | `image2/user-server/app/api/routes/catalog.py` |

---

## 12. FAQ

**Q: 直接传 `resolution: "4k"` 给 `/v1/images/generations` 行不行？**  
A: 不行/无效。网关要的是 `size: "3840x2160"` 这种。`resolution` 是产品层字段。

**Q: 4k 是否等于原生 4k 扩散模型？**  
A: 当前默认链路是「上游可生成尺寸出图 + 后处理放大」。不是单独的原生 4k 模型接口。

**Q: 为什么 2k/4k 有时几乎和 1k 一样慢或更慢很多？**  
A: 上游生成时间通常占大头；后处理放大叠加上传/下载/排队。4k 像素更大，后处理与存储更重。

**Q: 图生图原图是链接还是上传？**  
A:  
- 调 **4k-image-api**：三种都行（文件 / base64 / URL）  
- 调 **chatgpt2api 下游**：最终是 **multipart 文件**  
- **image2 产品层**：目前自己读图后 **multipart 上传**

**Q: 超分接口在哪？**  
A: 没有独立超分 API。见 `docs/super-resolution-api.md`。

---

（完）

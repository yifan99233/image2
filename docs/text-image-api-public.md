# 文生图 / 图生图 API 使用文档

> 版本：2026-07-13  
> 适用：OpenAI 兼容图片接口  
> 说明：本文只描述**如何调用**（传什么、怎么传），不涉及服务内部实现。

---

## 1. 接入信息

### Base URL

```text
https://<your-host>/v1
```

本地调试示例：

```text
http://localhost:4000/v1
```

### 鉴权

```http
Authorization: Bearer <YOUR_API_KEY>
```

或：

```http
x-api-key: <YOUR_API_KEY>
```

### 接口一览

| 能力 | 方法 | 路径 |
| --- | --- | --- |
| 文生图 | `POST` | `/v1/images/generations` |
| 图生图 / 图像编辑 | `POST` | `/v1/images/edits` |
| 查询可用模型 | `GET` | `/v1/models` |

---

## 2. 调用约定（请按模板传参）

### 2.1 模型

图片能力请使用图片模型，例如：

- `gpt-image-2`

### 2.2 尺寸怎么传（重要）

**统一使用 OpenAI 兼容字段 `size`。**  
不要传 `resolution` / `aspect_ratio` 给本接口（产品 UI 可以选 1k/2k/4k + 比例，但调用前必须映射成 `size`）。

格式：

```text
"{width}x{height}"
```

**请不要让终端用户自由输入任意分辨率。**  
UI 只提供「分辨率档位 + 画面比例」，后端按下方白名单映射为唯一 `size`。

#### 推荐白名单

##### 1k

| 比例 | size（请原样使用） |
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

| 比例 | size（请原样使用） |
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

| 比例 | size（请原样使用） |
| --- | --- |
| 1:1 | `3840x3840` |
| 4:3 | `3840x2880` |
| 3:4 | `2880x3840` |
| 16:9 | `3840x2160` |
| 9:16 | `2160x3840` |
| 3:2 | `3840x2560` |
| 2:3 | `2560x3840` |
| 21:9 | `3696x1584` |

#### UI / 接入映射建议

| 用户看到的选项 | 你实际传给接口的字段 |
| --- | --- |
| 分辨率：1k / 2k / 4k | **不要**直接传 `1k`，映射成上表 `size` |
| 比例：1:1 / 16:9 / ... | 与分辨率组合后取上表唯一 `size` |
| 自定义宽高输入框 | **不建议开放** |

正确示例：

```json
{ "size": "1024x1024" }
{ "size": "2048x1152" }
{ "size": "3840x2160" }
```

错误示例（不要这样）：

```json
{ "size": "1234x5678" }
{ "resolution": "4k" }
{ "aspect_ratio": "16:9" }
{ "width": 3840, "height": 2160 }
```

说明：上游网关（如 Sub2API）按 **`size` 字符串** 识别 1K/2K/4K 计费档；只传 `resolution` 不会被识别，可能按默认 2K 计费。


### 2.3 返回格式

| `response_format` | 含义 |
| --- | --- |
| `url` | 返回图片 URL（推荐） |
| `b64_json` | 返回 base64 |

---

## 3. OpenAI 兼容通用模板

下面模板与 OpenAI Images API 写法一致，可直接套用。

### 3.1 文生图模板（JSON）

```http
POST /v1/images/generations
Content-Type: application/json
Authorization: Bearer $OPENAI_API_KEY
```

```json
{
  "model": "gpt-image-2",
  "prompt": "your text prompt",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

可选字段（与 OpenAI 兼容，可按需附加）：

```json
{
  "model": "gpt-image-2",
  "prompt": "your text prompt",
  "n": 1,
  "size": "1024x1024",
  "quality": "auto",
  "response_format": "url",
  "user": "user-123"
}
```

### 3.2 图生图模板 A：JSON + 图片 URL（推荐）

```http
POST /v1/images/edits
Content-Type: application/json
Authorization: Bearer $OPENAI_API_KEY
```

```json
{
  "model": "gpt-image-2",
  "prompt": "your edit instruction",
  "image": "https://example.com/source.png",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

### 3.3 图生图模板 B：multipart 文件上传（OpenAI 常见写法）

```http
POST /v1/images/edits
Authorization: Bearer $OPENAI_API_KEY
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 示例值 |
| --- | --- |
| `model` | `gpt-image-2` |
| `prompt` | `your edit instruction` |
| `image` | 文件本体（`@source.png`） |
| `n` | `1` |
| `size` | `1024x1024` |
| `response_format` | `url` |
| `mask` | 可选，蒙版文件 |

curl：

```bash
curl "https://<your-host>/v1/images/edits" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -F "model=gpt-image-2" \
  -F "prompt=your edit instruction" \
  -F "n=1" \
  -F "size=1024x1024" \
  -F "response_format=url" \
  -F "image=@source.png;type=image/png"
```

### 3.4 图生图模板 C：JSON + base64 / data URL

```json
{
  "model": "gpt-image-2",
  "prompt": "your edit instruction",
  "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

也支持纯 base64（不带 data URL 前缀）：

```json
{
  "model": "gpt-image-2",
  "prompt": "your edit instruction",
  "image": "iVBORw0KGgoAAAANSUhEUgAA...",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

### 3.5 兼容扩展写法（可选）

以下写法同样可被接受，便于对接不同 SDK：

```json
{
  "model": "gpt-image-2",
  "prompt": "your edit instruction",
  "image": { "url": "https://example.com/source.png" },
  "size": "1024x1024",
  "response_format": "url"
}
```

```json
{
  "model": "gpt-image-2",
  "prompt": "your edit instruction",
  "image": { "image_url": "https://example.com/source.png" },
  "size": "1024x1024",
  "response_format": "url"
}
```

```json
{
  "model": "gpt-image-2",
  "prompt": "your edit instruction",
  "image": { "image_url": { "url": "https://example.com/source.png" } },
  "size": "1024x1024",
  "response_format": "url"
}
```

多图：

```json
{
  "model": "gpt-image-2",
  "prompt": "combine references",
  "image": [
    "https://example.com/a.png",
    "https://example.com/b.png"
  ],
  "size": "1024x1024",
  "response_format": "url"
}
```

---

## 4. 文生图

### 4.1 接口

```http
POST /v1/images/generations
Content-Type: application/json
Authorization: Bearer <YOUR_API_KEY>
```

### 4.2 参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 是 | 如 `gpt-image-2` |
| `prompt` | string | 是 | 文本提示词 |
| `size` | string | 建议必填 | **仅使用白名单 size**（见 §2.2） |
| `n` | number | 否 | 建议 `1` |
| `quality` | string | 否 | 如 `auto`、`high` |
| `response_format` | string | 否 | `url` / `b64_json`，推荐 `url` |
| `user` | string | 否 | 终端用户标识（OpenAI 兼容） |

### 4.3 示例：按档位调用

#### 1k / 1:1

```json
{
  "model": "gpt-image-2",
  "prompt": "一只玻璃质感的小机器人撑红伞，白底产品渲染",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

#### 2k / 16:9

```json
{
  "model": "gpt-image-2",
  "prompt": "城市夜景广角，霓虹倒影",
  "n": 1,
  "size": "2048x1152",
  "response_format": "url"
}
```

#### 4k / 16:9

```json
{
  "model": "gpt-image-2",
  "prompt": "超清山脉日出航拍",
  "n": 1,
  "size": "3840x2160",
  "response_format": "url"
}
```

### 4.4 curl

```bash
curl "https://<your-host>/v1/images/generations" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "A clean product photo of a glass robot",
    "n": 1,
    "size": "1024x1024",
    "response_format": "url"
  }'
```

### 4.5 成功响应

```json
{
  "created": 1720000000,
  "data": [
    {
      "url": "https://example.com/path/to/result.png"
    }
  ]
}
```

`b64_json` 时：

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

## 5. 图生图 / 图像编辑

### 5.1 接口

```http
POST /v1/images/edits
Authorization: Bearer <YOUR_API_KEY>
```

`Content-Type` 可选：

- `application/json`
- `multipart/form-data`

### 5.2 参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `model` | string | 是 | 如 `gpt-image-2` |
| `prompt` | string | 是 | 编辑说明 |
| `image` | file / string / object / array | 是 | 原图 |
| `mask` | file / string / object | 否 | 蒙版图 |
| `size` | string | 建议必填 | **仅使用白名单 size**（见 §2.2） |
| `n` | number | 否 | 建议 `1` |
| `quality` | string | 否 | 质量参数 |
| `response_format` | string | 否 | `url` / `b64_json` |
| `user` | string | 否 | 终端用户标识 |

### 5.3 原图 `image` 传法

| 方式 | 何时用 | 怎么写 |
| --- | --- | --- |
| 图片 URL | 原图已在公网/CDN | `"image":"https://.../a.png"` |
| 文件上传 | 本地文件、表单上传 | multipart 字段 `image` |
| base64 / data URL | 不便暴露公网链接 | `"image":"data:image/png;base64,..."` |

建议优先级：

1. **公网 URL**（最快、请求体最小）
2. 文件上传
3. base64（大图慎用）

要求：

- URL 必须可访问
- 建议 `png` / `jpeg` / `webp`
- 无法访问的链接、空内容、非法格式会返回 `400`

### 5.4 示例

#### 链接图生图 + 2k 正方形

```json
{
  "model": "gpt-image-2",
  "prompt": "轻微增强细节，保持构图不变",
  "image": "https://example.com/source.png",
  "n": 1,
  "size": "2048x2048",
  "response_format": "url"
}
```

#### 文件上传 + 1k

```bash
curl "https://<your-host>/v1/images/edits" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -F "model=gpt-image-2" \
  -F "prompt=轻微增强细节，保持构图不变" \
  -F "n=1" \
  -F "size=1024x1024" \
  -F "response_format=url" \
  -F "image=@./source.png;type=image/png"
```

#### base64 + 4k 16:9

```json
{
  "model": "gpt-image-2",
  "prompt": "提升清晰度，保留主体",
  "image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
  "n": 1,
  "size": "3840x2160",
  "response_format": "url"
}
```

### 5.5 成功响应

与文生图相同：

```json
{
  "created": 1720000000,
  "data": [
    {
      "url": "https://example.com/path/to/result.png"
    }
  ]
}
```

---

## 6. 查询模型

```http
GET /v1/models
Authorization: Bearer <YOUR_API_KEY>
```

---

## 7. 错误返回

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

| 现象 | 可能原因 | 处理 |
| --- | --- | --- |
| 401 / 403 | Key 错误或缺失 | 检查鉴权头 |
| 400 `invalid_image` | 原图非法 / URL 不可访问 | 检查 `image` |
| 404 `model_not_found` | 模型名错误 | 改用 `gpt-image-2` 等可用模型 |
| 超时 / 很慢 | 图片过大或 size 过大 | 优先 URL；先用 1k/2k 白名单 |

---

## 8. 接入方实现清单（推荐）

1. UI 只给：
   - 分辨率：`1k` / `2k` / `4k`
   - 比例：`1:1` `4:3` `3:4` `16:9` `9:16` `3:2` `2:3` `21:9`
2. 后端/前端用白名单表映射出唯一 **`size`**（不要把 `resolution` 直接传给接口）
3. 文生图调用 `/v1/images/generations`
4. 图生图调用 `/v1/images/edits`
5. 请求保持 OpenAI 字段名：
   - `model`
   - `prompt`
   - `image`（仅图生图）
   - `size`
   - `n`
   - `response_format`
6. 不要开放自由宽高输入框
7. 计费侧（Sub2API 等）也只认 `size`，统一走 `size` 可保证 1K/2K/4K 识别一致

---

## 9. 最小可用模板（可直接复制）

### 文生图

```json
{
  "model": "gpt-image-2",
  "prompt": "一只猫坐在窗台上",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

### 图生图

```json
{
  "model": "gpt-image-2",
  "prompt": "增强细节，保持原构图",
  "image": "https://example.com/source.png",
  "n": 1,
  "size": "2048x2048",
  "response_format": "url"
}
```

### 一键对照

| 场景 | method/path | 关键字段 |
| --- | --- | --- |
| 文生图 | `POST /v1/images/generations` | `model, prompt, size` |
| 图生图 | `POST /v1/images/edits` | `model, prompt, image, size` |

---

如需生产域名、测试 Key 或模型白名单，请联系服务提供方。

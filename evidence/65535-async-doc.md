# 65535 原生异步任务 API：`/v1/tasks`

本文介绍 65535 原生异步任务接口 `v1/tasks` 的调用方式。该接口使用统一的任务信封提交图片或视频任务，并通过轮询或回调取得结果。

> 当前支持的任务类型是 `image` 和 `video`。模型、价格、在线状态和账号权限均可能动态变化，请在调用前通过 `/v1/models` 与 `/v1/pricing` 查询，不要把示例模型名写成永久白名单。

## 1. 基本信息

```text
Base URL: https://task-api-1-cn.65535.space
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

建议将密钥放在环境变量中，不要写入代码仓库：

```bash
export S65535_API_KEY="你的 API Key"
export S65535_BASE_URL="https://task-api-1-cn.65535.space"
```

所有请求都使用：

```http
Authorization: Bearer $S65535_API_KEY
```

## 2. 接口一览

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/v1/tasks` | 创建图片或视频异步任务 |
| `GET` | `/v1/tasks/{id}` | 查询单个任务及结果 |
| `GET` | `/v1/tasks` | 分页查询任务记录 |
| `GET` | `/v1/models` | 查询当前 API Key 可用的模型 |
| `GET` | `/v1/pricing` | 查询模型类型、价格、在线状态和端点 |

典型流程：

```text
查询模型 -> POST 创建任务 -> 保存 id -> 每隔约 2 秒 GET 查询 -> done/failed 后停止
```

也可以在创建任务时传入 `callback_url`，由服务端在任务结束后主动通知。

## 3. 查询和选择模型

### 3.1 查询当前 Key 可用的模型

```bash
curl -sS "$S65535_BASE_URL/v1/models" \
  -H "Authorization: Bearer $S65535_API_KEY"
```

响应示例：

```json
{
  "object": "list",
  "data": [
    {
      "id": "gpt-image-2",
      "object": "model",
      "name": "gpt-image-2",
      "capabilities": ["image"]
    }
  ]
}
```

`/v1/models` 会根据 API Key 所属分组过滤模型，因此实际调用时建议始终携带密钥。

### 3.2 查询模型类型、价格和在线状态

```bash
curl -sS "$S65535_BASE_URL/v1/pricing" \
  -H "Authorization: Bearer $S65535_API_KEY"
```

重点字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 请求中的模型 ID |
| `online` | 当前是否有可用渠道或 Worker |
| `endpoints` | 可调用类型，如 `image`、`video`、`openai` |
| `mode` | 计费模式，如按次、按秒、按用量或混合计费 |
| `per_request_micro` | 单次基础价格，单位为微美元，`1000000` 等于 `$1` |
| `per_second_micro` | 每秒价格，常用于视频 |
| `size_prices` | 不同尺寸或清晰度的价格 |
| `description`、`provider`、`tags` | 模型说明、提供方和标签 |

使用 `jq` 筛选图片模型：

```bash
curl -sS "$S65535_BASE_URL/v1/pricing" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  | jq '(.data // .) | map(select(.online == true and ((.endpoints // []) | index("image"))))'
```

筛选视频模型：

```bash
curl -sS "$S65535_BASE_URL/v1/pricing" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  | jq '(.data // .) | map(select(.online == true and ((.endpoints // []) | index("video"))))'
```

> `/v1/models` 解决“这个 Key 能不能看到并使用模型”，`/v1/pricing` 解决“模型是什么类型、是否在线、如何计费”。提交前最好同时满足：模型在 `/v1/models` 中，并且 `/v1/pricing` 显示对应的 `image` 或 `video` 端点。

### 3.3 模型类型和常见示例

下表中的名称是常见配置或代码兼容示例，不代表每个账号当前一定可用。

| 类型 | `kind` | 常见模型示例 | 主要用途 |
| --- | --- | --- | --- |
| GPT Image 系列 | `image` | `gpt-image-2`、`gpt-image-2-auto`、`gpt-image-2-n`、`gpt-image-2-eco` | 文生图、参考图编辑、多图参考、部分渠道支持蒙版 |
| Gemini Image 系列 | `image` | `gemini-3-pro-image`、`gemini-3.1-flash-image` | 文生图、参考图生成；原生调用通常单次返回 1 张 |
| xAI 视频 | `video` | `grok-imagine-video` | 文生视频、首帧生视频、参考图生视频，部分配置支持编辑和扩展 |
| OpenAI 形状视频 | `video` | `sora-2` 等部署配置 | 文生视频、首帧生视频；具体能力取决于上游渠道 |
| Seedance / MiniMax | `video` | 以 `/v1/models` 返回值为准 | 文生视频、首尾帧、风格参考；支持范围由模型和渠道决定 |

注意：

- 不要只根据模型名后缀推断能力或价格，例如 `-auto`、`-eco`、`-n` 的实际策略由部署配置决定。
- `gpt-image-2` 是省略 `kind=image` 时的默认图片模型。
- `grok-imagine-video` 是省略 `kind=video` 的 `model` 时的默认视频模型，但生产代码仍建议明确传入模型。
- 文本聊天、Embedding、音频等模型即使出现在 `/v1/models`，也不能作为当前 `/v1/tasks` 的任务类型；当前原生任务只接受 `image` 和 `video`。

## 4. 创建任务

### 4.1 通用请求结构

```http
POST /v1/tasks
```

```json
{
  "kind": "image",
  "model": "gpt-image-2",
  "operation": "generate",
  "input": {
    "prompt": "任务提示词"
  },
  "callback_url": "https://example.com/webhooks/65535"
}
```

顶层字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `kind` | string | 否 | `image` 或 `video`；省略时默认为 `image` |
| `model` | string | 否 | 模型 ID；建议显式传入 |
| `operation` | string | 视频部分场景 | 视频操作：`generate`、`edit`、`extend`；图片忽略该字段 |
| `input` | object | 是 | 传给具体任务类型的参数对象 |
| `callback_url` | string | 否 | 任务结束回调地址；必须是服务端可访问的公网 HTTP(S) 地址 |

不要传 `path`。上游调用路径由 `kind` 和 `operation` 自动决定，属于服务端内部路由信息。

### 4.2 创建响应

成功创建返回 HTTP `202 Accepted`：

```json
{
  "id": "img_4a9da3cd",
  "kind": "image",
  "status": "pending",
  "status_url": "/v1/tasks/img_4a9da3cd"
}
```

应立即保存 `id`。创建成功只表示任务已经入队，不表示生成已经完成。

### 4.3 幂等提交

网络超时后直接重新 `POST` 可能创建重复任务。建议为每次业务请求生成唯一的 `Idempotency-Key`：

```bash
curl -sS "$S65535_BASE_URL/v1/tasks" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-20260804-0001" \
  --data-binary @request.json
```

同一凭证、同一路径、同一请求体和同一幂等键在有效期内会复用首次响应。并发重复提交尚未结束时可能返回 `409`。

## 5. 图片任务：`kind=image`

### 5.1 图片输入参数

| `input` 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `prompt` | string | 是 | 生成或编辑要求，不能为空 |
| `size` | string | 否 | 比例、像素尺寸或预设名，如 `16:9`、`1024x1024`、`square_hd` |
| `resolution` | string | 否 | 清晰度档位，如 `1k`、`2k`、`4k`；与比例组合使用 |
| `quality` | string | 否 | 质量档位，允许值取决于模型和渠道 |
| `n` | integer | 否 | 期望图片数，默认 `1`；模型可能有自己的数量限制 |
| `response_format` | string | 否 | `url` 或 `b64_json`；推荐默认 URL |
| `image` | string/array | 否 | 单张或多张参考图 |
| `image_url` | string | 否 | 单张参考图 URL 或 data URI |
| `image_urls` | array | 否 | 多张参考图，最多处理 16 张 |
| `images` | array | 否 | `image_urls` 的兼容写法 |
| `mask` | string | 否 | 蒙版 URL 或 data URI；仅部分图片模型/渠道支持 |

未列出的图片供应商参数会尽量原样保留并传给上游，但是否生效由所选模型决定。

### 5.2 文生图

```bash
curl -sS "$S65535_BASE_URL/v1/tasks" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: image-demo-001" \
  --data-binary @- <<'JSON'
{
  "kind": "image",
  "model": "gpt-image-2",
  "input": {
    "prompt": "一只橘猫坐在未来城市的屋顶，电影感夜景，蓝紫色霓虹，细节清晰",
    "size": "16:9",
    "resolution": "2k",
    "n": 1
  }
}
JSON
```

### 5.3 尺寸和分辨率

支持三类写法：

```json
{ "size": "16:9", "resolution": "2k" }
```

```json
{ "size": "1536x1024" }
```

```json
{ "size": "landscape_16_9", "resolution": "4k" }
```

规则：

- 显式像素尺寸优先，不会被服务端尺寸表覆盖。
- 比例加档位会按模型解析成具体像素；同样的“`4k + 16:9`”在不同模型上可能对应不同像素尺寸。
- 只传 `resolution` 时表示该档位的方图。
- 只传比例但不传 `resolution` 时，当前历史默认档位是 `2k`。
- 两者都不传时，不强行指定尺寸，使用模型或渠道默认值。
- `size: "auto"` 等供应商自定义值会尽量原样保留，不建议同时再传互相冲突的 `resolution`。

## 6. 图片参考图

参考图可以是：

- 公网可访问的 `https://` 或 `http://` URL；
- `data:image/...;base64,...` data URI；
- 兼容裸 base64，但不推荐，推荐始终携带 MIME 类型组成 data URI。

URL 必须能被 65535 服务端访问。内网地址、`localhost`、短期失效的签名 URL、需要 Cookie 的地址通常不可用。

### 6.1 单张参考图

推荐使用 `input.image`：

```bash
curl -sS "$S65535_BASE_URL/v1/tasks" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @- <<'JSON'
{
  "kind": "image",
  "model": "gpt-image-2",
  "input": {
    "prompt": "保留人物姿势和服装轮廓，将背景改成雨夜东京街头，写实摄影",
    "image": "https://cdn.example.com/reference/person.png",
    "size": "3:4",
    "resolution": "2k",
    "n": 1
  }
}
JSON
```

`image_url` 也可表示单张参考图：

```json
{
  "input": {
    "prompt": "转换为水彩插画",
    "image_url": "https://cdn.example.com/reference/photo.jpg"
  }
}
```

### 6.2 多张参考图

推荐使用 `image_urls` 数组：

```json
{
  "kind": "image",
  "model": "gpt-image-2",
  "input": {
    "prompt": "使用第一张图的人物，第二张图的服装，第三张图的室内配色，生成一张时尚杂志封面",
    "image_urls": [
      "https://cdn.example.com/ref/person.png",
      "https://cdn.example.com/ref/clothes.png",
      "https://cdn.example.com/ref/palette.png"
    ],
    "size": "3:4",
    "resolution": "2k"
  }
}
```

最多处理 16 张参考图。为了获得稳定结果，建议在提示词中明确每张图的用途和优先级，不要只写“参考这些图片”。

### 6.3 URL 与 data URI 混用

```json
{
  "input": {
    "prompt": "融合两张参考图的视觉风格",
    "image_urls": [
      "https://cdn.example.com/ref/a.png",
      "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ..."
    ]
  }
}
```

不要在日志中打印完整 data URI。base64 会明显增大请求体，图片较大时优先使用稳定的公网对象存储 URL。

### 6.4 将本地图片转为 data URI

macOS / Linux：

```bash
REF_DATA_URI="data:image/png;base64,$(base64 < ./reference.png | tr -d '\n')"
```

使用 `jq` 安全构造 JSON，避免提示词和 base64 中的字符破坏请求体：

```bash
jq -n \
  --arg image "$REF_DATA_URI" \
  --arg prompt "保留构图，将画面改为赛博朋克风格" \
  '{
    kind: "image",
    model: "gpt-image-2",
    input: {
      prompt: $prompt,
      image: $image,
      size: "16:9",
      resolution: "2k",
      n: 1
    }
  }' > request.json

curl -sS "$S65535_BASE_URL/v1/tasks" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @request.json
```

### 6.5 蒙版编辑

```json
{
  "kind": "image",
  "model": "gpt-image-2",
  "input": {
    "prompt": "只修改蒙版区域，在桌面上增加一束白色郁金香",
    "image": "https://cdn.example.com/ref/room.png",
    "mask": "https://cdn.example.com/ref/room-mask.png",
    "size": "1024x1024"
  }
}
```

蒙版是否生效取决于模型和上游渠道。OpenAI 图片编辑形状可以把蒙版作为独立文件发送；Gemini 原生图片生成没有等价蒙版参数，因此使用 Gemini 图片模型时不要依赖局部蒙版编辑。

### 6.6 参考图限制和失败行为

- 最多尝试解析 16 张参考图。
- 单张参考图和全部参考媒体的解码后大小都有服务端上限；当前图片参考媒体总预算为 256 MiB。
- 原生图片任务 JSON 请求体上限当前约为 360 MiB，base64 会产生约三分之一的体积膨胀。
- 推荐 PNG、JPEG 或 WebP。不同模型对 GIF 等格式的支持可能不同。
- 如果请求明确携带参考图，但所有参考图都无法下载或解析，任务会失败，不会静默退化为普通文生图并收费。
- 常见相关错误码包括 `reference_image_unfetchable`、`reference_media_unusable` 和 `invalid_request`。

## 7. 不同图片模型的行为差异

客户端请求信封保持一致，但不同模型的实际能力不完全相同：

| 能力 | GPT Image / OpenAI 形状渠道 | Gemini Image 原生渠道 |
| --- | --- | --- |
| 文生图 | 支持 | 支持 |
| 单图参考 | 自动转为图片编辑请求 | 参考图作为 `inlineData` 与提示词一起发送 |
| 多图参考 | 通常使用重复的图片文件字段 | 多张图作为多个 `inlineData` 内容块 |
| 蒙版 | 部分模型/渠道支持 | 无原生等价参数，不应依赖 |
| `n > 1` | 由模型决定，常见图片 API 可支持多张 | 原生 `generateContent` 单次通常只返回 1 张 |
| 尺寸 | 常见为具体像素 | 常见为清晰度档位加宽高比 |

因此业务代码应：

1. 通过 `/v1/models` 和 `/v1/pricing` 选择模型；
2. 只发送业务真正需要的参数；
3. 不假设同一个参数在所有模型上效果完全一致；
4. 以最终任务响应中的 `size`、`image_size_tier`、`image_count` 和 `result_urls` 为准。

## 8. 视频任务：`kind=video`

### 8.1 视频输入参数

| `input` 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `prompt` | string | 是 | 视频内容或编辑指令 |
| `seconds` | integer/string | 否 | 视频时长，可传 `8` 或 `"8"`；默认 `4` 秒 |
| `duration` | integer/string | 否 | 部分供应商的兼容写法；未传 `seconds` 时可作为时长 |
| `size` | string | 否 | 如 `1280x720`、`720x1280` 或比例 |
| `aspect_ratio` | string | 否 | 如 `16:9`、`9:16`、`1:1` |
| `resolution` | string | 否 | 如 `720p`、`1080p`、`4k`；支持范围取决于模型 |
| `input_reference` | object | 否 | 首帧图片，常用形状为 `{ "image_url": "..." }` |
| `reference_image_urls` | array | 否 | 风格、主体等参考图，不表示首帧 |
| `input_mode` | string | 否 | 明确图片角色：`first_frame` 或 `reference` |
| `last_frame_url` | string | 否 | 尾帧图片，部分模型支持 |
| `video` | object/string | 编辑/扩展必填 | 源视频 URL、data URI，或本 API 已有视频的任务 ID |
| `video_url` | string | 编辑/扩展兼容字段 | 源视频 URL |

视频 JSON 输入当前上限为 64 MiB。大视频不要直接塞入 data URI，建议使用稳定的公网 URL；需要上传文件时可使用专用 `/v1/videos/edits` multipart 接口。

### 8.2 文生视频

```bash
curl -sS "$S65535_BASE_URL/v1/tasks" \
  -H "Authorization: Bearer $S65535_API_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @- <<'JSON'
{
  "kind": "video",
  "model": "grok-imagine-video",
  "operation": "generate",
  "input": {
    "prompt": "电影镜头：一辆复古跑车沿海岸公路行驶，日落，镜头缓慢跟随",
    "seconds": 8,
    "aspect_ratio": "16:9",
    "resolution": "720p"
  }
}
JSON
```

### 8.3 首帧生视频

首帧是输出视频的第 0 帧，会影响构图和比例：

```json
{
  "kind": "video",
  "model": "grok-imagine-video",
  "operation": "generate",
  "input": {
    "prompt": "人物转身看向镜头，头发被微风吹动，镜头轻微推进",
    "seconds": 6,
    "input_mode": "first_frame",
    "input_reference": {
      "image_url": "https://cdn.example.com/video/start-frame.png"
    }
  }
}
```

也兼容单个 `image_url` 或 `image`。显式传 `input_mode: "first_frame"` 可以避免供应商字段歧义。

### 8.4 参考图生视频

参考图用于指导人物、产品或画面风格，并不要求成为视频首帧：

```json
{
  "kind": "video",
  "model": "grok-imagine-video",
  "operation": "generate",
  "input": {
    "prompt": "生成品牌短片，保持参考图中的产品外形、材质和主色调",
    "seconds": 8,
    "aspect_ratio": "16:9",
    "resolution": "720p",
    "input_mode": "reference",
    "reference_image_urls": [
      "https://cdn.example.com/product/front.png",
      "https://cdn.example.com/product/side.png"
    ]
  }
}
```

关键区别：

| 目的 | 推荐字段 | `input_mode` |
| --- | --- | --- |
| 图片就是输出视频的首帧 | `input_reference.image_url` | `first_frame` |
| 图片只指导主体或风格 | `reference_image_urls` | `reference` |

即使只有一张风格参考图，也建议使用数组字段 `reference_image_urls`；“一张数组参考图”仍然是参考模式，不应自动解释为首帧。

### 8.5 视频编辑

```json
{
  "kind": "video",
  "model": "grok-imagine-video",
  "operation": "edit",
  "input": {
    "prompt": "保持镜头运动，将天气改为下雪，增强电影感",
    "video": {
      "url": "https://cdn.example.com/video/source.mp4"
    }
  }
}
```

也可以引用当前账号通过本 API 生成的视频任务：

```json
{
  "video": {
    "id": "vid_abc123"
  }
}
```

### 8.6 视频扩展

```json
{
  "kind": "video",
  "model": "grok-imagine-video",
  "operation": "extend",
  "input": {
    "prompt": "镜头继续向前移动，城市天际线逐渐出现在远处",
    "seconds": 8,
    "video": {
      "url": "https://cdn.example.com/video/source.mp4"
    }
  }
}
```

`edit` 和 `extend` 不是所有视频模型都支持。模型在线不等于支持所有操作；不支持时任务会在提交校验或渠道能力校验阶段被拒绝。

## 9. 查询单个任务

```bash
TASK_ID="img_4a9da3cd"

curl -sS "$S65535_BASE_URL/v1/tasks/$TASK_ID" \
  -H "Authorization: Bearer $S65535_API_KEY"
```

### 9.1 状态值

| 状态 | 含义 | 客户端行为 |
| --- | --- | --- |
| `pending` | 已入队，尚未开始 | 继续等待 |
| `running` | 正在处理，或等待内部重试 | 继续等待 |
| `done` | 成功完成 | 读取结果并停止轮询 |
| `failed` | 最终失败 | 读取错误并停止轮询，不要自动创建替代任务 |

推荐每隔约 2 秒轮询一次；长视频可逐步放大到 5 秒，避免高频请求。

### 9.2 图片任务完成响应

```json
{
  "id": "img_4a9da3cd",
  "kind": "image",
  "status": "done",
  "model": "gpt-image-2",
  "prompt": "一只橘猫坐在未来城市的屋顶",
  "size": "2048x1152",
  "quality": "",
  "n": 1,
  "image_count": 1,
  "image_size_tier": "2K",
  "result_urls": [
    "https://cdn.example.com/generated/img_4a9da3cd_0.png"
  ],
  "result_file_sizes": [2345678],
  "error_code": "",
  "error_message": "",
  "cost_usd": 0.04,
  "retry_count": 0,
  "queue_ms": 120,
  "retry_ms": 0,
  "upstream_ms": 18420,
  "created_at": "2026-08-04T10:00:00Z",
  "started_at": "2026-08-04T10:00:01Z",
  "finished_at": "2026-08-04T10:00:19Z",
  "expires_at": "2026-08-05T10:00:19Z"
}
```

时间字段可能为 `null`，例如任务尚未开始时没有 `started_at`。

如果请求传了 `response_format: "b64_json"`，详情查询成功后还可能包含：

```json
{
  "result": {
    "created": 1785818400,
    "data": [
      { "b64_json": "iVBORw0KGgoAAA..." }
    ]
  }
}
```

即使要求 base64，响应也可能保留 `result_urls`。客户端应优先读取自己需要的格式，并避免记录完整 base64。

### 9.3 视频任务完成响应

```json
{
  "id": "vid_abc123",
  "kind": "video",
  "operation": "generate",
  "status": "done",
  "model": "grok-imagine-video",
  "prompt": "一辆复古跑车沿海岸公路行驶",
  "seconds": 8,
  "size": "1280x720",
  "progress": 100,
  "video_url": "https://cdn.example.com/generated/vid_abc123.mp4",
  "result_urls": [
    "https://cdn.example.com/generated/vid_abc123.mp4"
  ],
  "download_url": "/v1/videos/vid_abc123/content",
  "cost_usd": 0.32,
  "error_code": "",
  "error_message": "",
  "created_at": "2026-08-04T10:00:00Z",
  "started_at": "2026-08-04T10:00:02Z",
  "finished_at": "2026-08-04T10:02:10Z"
}
```

### 9.4 失败响应

任务本身失败时，查询接口通常仍返回 HTTP `200`，失败信息位于任务文档中：

```json
{
  "id": "img_failed123",
  "kind": "image",
  "status": "failed",
  "model": "gpt-image-2",
  "result_urls": [],
  "error_code": "reference_image_unfetchable",
  "error_message": "the reference image could not be fetched from the URL supplied",
  "cost_usd": 0
}
```

失败任务不计费。客户端判断任务是否成功必须检查 JSON 中的 `status`，不能只检查查询请求的 HTTP 状态码。

## 10. 查询任务列表

```bash
curl -sS "$S65535_BASE_URL/v1/tasks?kind=image&status=done&page=1&page_size=20" \
  -H "Authorization: Bearer $S65535_API_KEY"
```

查询参数：

| 参数 | 说明 |
| --- | --- |
| `kind` | `image` 或 `video` |
| `status` | `pending`、`running`、`done`、`failed` |
| `since` | 起始时间，RFC3339 或 Unix 秒 |
| `until` | 结束时间，RFC3339 或 Unix 秒 |
| `page` | 页码，从 `1` 开始 |
| `page_size` | 每页数量，默认 `100`，最大按 `500` 处理 |

时间示例：

```bash
curl -sS "$S65535_BASE_URL/v1/tasks?kind=video&since=2026-08-01T00:00:00Z&until=2026-08-05T00:00:00Z&page=1&page_size=100" \
  -H "Authorization: Bearer $S65535_API_KEY"
```

Unix 时间必须使用秒，不要直接传 JavaScript `Date.now()` 返回的毫秒值。

列表响应：

```json
{
  "data": [
    {
      "id": "img_4a9da3cd",
      "kind": "image",
      "status": "done",
      "model": "gpt-image-2",
      "result_urls": ["https://cdn.example.com/generated/a.png"]
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

列表响应会省略或投影大型字段，不应用它代替单任务详情接口。

## 11. 回调通知

创建任务时传入：

```json
{
  "callback_url": "https://api.example.com/webhooks/65535"
}
```

终态回调使用 HTTP `POST`，`Content-Type: application/json`。当前公共回调体采用统一的媒体任务形状：

```json
{
  "request_id": "img_4a9da3cd",
  "status": "done",
  "model": "gpt-image-2",
  "size": "2048x1152",
  "image_size_tier": "2K",
  "image_count": 1,
  "result_urls": [
    "https://cdn.example.com/generated/a.png"
  ],
  "error_code": "",
  "error_message": "",
  "cost_usd": 0.04
}
```

失败时：

```json
{
  "request_id": "img_failed123",
  "status": "failed",
  "model": "gpt-image-2",
  "size": "2048x1152",
  "image_size_tier": "",
  "image_count": 0,
  "result_urls": [],
  "error_code": "upstream_error",
  "error_message": "the request could not be completed upstream",
  "cost_usd": 0
}
```

回调集成建议：

- 回调处理必须幂等，以 `request_id` 作为业务去重键。
- 收到回调后可以再调用 `GET /v1/tasks/{id}` 获取完整、按 `kind` 区分的任务文档；视频尤其建议这样做。
- 回调是尽力投递，接收端不可用时不保证无限重试，因此关键业务仍应保留轮询或定时补偿。
- 回调地址需要是公网 HTTP(S) 地址；默认安全策略会阻止指向私网或本机的 URL。
- 一个 `callback_url` 字符串可以用逗号或空白分隔多个地址，但最多通知 8 个。通常建议只传一个稳定的业务入口，由业务系统内部再分发。

## 12. 常见请求错误

创建、鉴权或参数校验失败时使用 OpenAI 风格错误信封：

```json
{
  "error": {
    "message": "input.prompt is required for kind=image",
    "type": "Bad Request"
  }
}
```

常见 HTTP 状态：

| HTTP 状态 | 含义 |
| --- | --- |
| `400` | JSON、`kind`、`operation`、提示词、比例或其他参数无效 |
| `401` | API Key 缺失或无效 |
| `402` | 余额不足以覆盖预估费用 |
| `403` | 分组无模型权限、异步任务未启用或内容策略拒绝 |
| `404` | 任务不存在，或当前 Key 无权查看该任务 |
| `409` | 相同幂等键的请求仍在处理中 |
| `413` | 请求体或参考媒体过大 |
| `429` | 并发、速率或任务上限触发 |
| `502` | 内部任务服务或上游暂时不可用 |
| `503` | 异步任务未启用、队列过长或当前无可用处理能力 |

错误处理原则：

- `POST` 没有明确返回任务 ID 时，使用同一个 `Idempotency-Key` 重试，不要换键重复创建。
- 查询返回 `pending` 或 `running` 时继续轮询。
- 查询返回 `failed` 时停止，不要自动再创建一个替代任务，除非业务明确允许且使用新的业务请求 ID。
- `result_urls` 可能有有效期，应在任务成功后及时下载或转存。

## 13. Python 完整示例

以下示例只依赖 `requests`：

```python
import os
import time
import uuid
import requests

BASE_URL = os.getenv("S65535_BASE_URL", "https://task-api-1-cn.65535.space")
API_KEY = os.environ["S65535_API_KEY"]

session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
})


def submit_task(payload: dict, business_id: str | None = None) -> dict:
    idem_key = business_id or str(uuid.uuid4())
    response = session.post(
        f"{BASE_URL}/v1/tasks",
        headers={"Idempotency-Key": idem_key},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def get_task(task_id: str) -> dict:
    response = session.get(f"{BASE_URL}/v1/tasks/{task_id}", timeout=30)
    response.raise_for_status()
    return response.json()


def wait_task(task_id: str, timeout_seconds: int = 900) -> dict:
    deadline = time.monotonic() + timeout_seconds
    interval = 2.0

    while time.monotonic() < deadline:
        task = get_task(task_id)
        status = task.get("status")

        if status == "done":
            return task
        if status == "failed":
            raise RuntimeError(
                f"task failed: {task.get('error_code')}: "
                f"{task.get('error_message')}"
            )
        if status not in {"pending", "running"}:
            raise RuntimeError(f"unknown task status: {status!r}")

        time.sleep(interval)
        interval = min(interval * 1.25, 5.0)

    raise TimeoutError(f"task {task_id} did not finish in time")


payload = {
    "kind": "image",
    "model": "gpt-image-2",
    "input": {
        "prompt": "根据参考图生成一张极简科技产品海报",
        "image_urls": [
            "https://cdn.example.com/reference/product.png",
            "https://cdn.example.com/reference/colors.png",
        ],
        "size": "3:4",
        "resolution": "2k",
        "n": 1,
    },
}

created = submit_task(payload, business_id="poster-order-10001")
result = wait_task(created["id"])

print("task id:", result["id"])
print("cost usd:", result.get("cost_usd"))
print("result urls:", result.get("result_urls", []))
```

## 14. 下载结果

```bash
RESULT_URL="https://cdn.example.com/generated/a.png"
curl -fL "$RESULT_URL" -o result.png
```

Python：

```python
from pathlib import Path
import requests


def download_file(url: str, output: str) -> None:
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with Path(output).open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)
```

## 15. 最佳实践清单

- 使用环境变量保存 API Key。
- 提交前查询 `/v1/models` 和 `/v1/pricing`，不要硬编码永久模型清单。
- 明确传 `kind` 和 `model`，避免默认值变化影响业务。
- 每个业务请求使用稳定、唯一的 `Idempotency-Key`。
- 参考图优先使用稳定的公网对象存储 URL；必须内联时使用带 MIME 的 data URI。
- 多图参考时在提示词中说明每张图片的角色。
- 视频图片输入显式传 `input_mode`，区分首帧和风格参考。
- 只把 `pending`、`running` 当作可继续等待状态。
- `failed` 后记录 `id`、`error_code` 和 `error_message`，不要记录 API Key 或完整 base64。
- 成功后尽快转存 `result_urls`，不要假设 URL 永久有效。
- 回调与轮询都按任务 ID 幂等处理，视频回调后再拉取一次详情。

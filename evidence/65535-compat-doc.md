为已按其他规范写好的客户端提供的兼容接口,底层与[原生 API](/docs/async-native-api) 是同一个任务引擎。

**新接入请用原生接口。** 这两套的字段名和状态值与原生不同,仅在你的客户端已经按对应规范实现时使用。

## APIMart 兼容

### 提交

```bash
curl https://your-host/apimart/v1/images/generations \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"gpt-image-2","prompt":"a neon cat","resolution":"1024x1024"}'
```

```json
{ "code": 200, "data": [ { "task_id": "img_9f2a...", "status": "submitted" } ] }
```

这个接口只返回任务 ID,不返回图片。

### 查询

```bash
curl https://your-host/apimart/v1/tasks/img_9f2a... \
  -H "Authorization: Bearer $KEY"
```

也支持 `/apimart/v1/images/tasks/{id}`,两者等价。

```json
{
  "code": 200,
  "data": {
    "id": "img_9f2a...",
    "status": "completed",
    "progress": 100,
    "created": 1784000031,
    "result": { "images": [ { "url": ["https://cdn.../0.png"] } ] }
  }
}
```

### 对接要点

| 项目 | 说明 |
| --- | --- |
| 任务 ID 字段 | 提交时是 `data[0].task_id`,查询时是 `data.id` |
| `data` 类型 | 提交时是数组,查询时是对象 |
| 图片地址 | `result.images[].url` 是**数组**,不是字符串 |
| 任务不存在 | 返回 `400`,不是 `404` |

状态值:

| APIMart | 对应原生 |
| --- | --- |
| `submitted` | `pending`(仅提交响应) |
| `processing` | `pending` / `running` |
| `completed` | `done` |
| `failed` | `failed` |

**任务失败时 HTTP 状态码仍是 `200`**,失败信息在 `data.status` 中。请勿仅凭 HTTP 状态码判断成败。

`response_format` 需要精确写作 `"b64_json"`,其他写法(`b64`、`base64`)会被忽略并返回 URL。

APIMart 接口没有任务列表,如需列表请使用 `GET /v1/tasks`。

## 65535-old 兼容

供迁移期的老客户端使用。响应格式:

```json
{ "code": 0, "message": "ok", "data": { ... } }
```

### 出图(同步 / 异步二选一)

```
POST /65535-old/v1/images/generations
```

带请求头 `X-Async-Mode: true` 返回任务句柄,不带则等待并返回图片。

> 若同时设置了 `"stream": true`,会走流式返回,`X-Async-Mode` 不生效。

### 专用异步路由

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/65535-old/v1/images/async-generations` | 提交(无需请求头) |
| `GET` | `/65535-old/v1/images/async-generations` | 列表 |
| `GET` | `/65535-old/v1/images/async-generations/{id}` | 查询单个 |

列表分页参数为 `page` / `page_size`,默认每页 20。

### 对接要点

任务对象的标识字段是 `job_id`,原生接口中对应 `id`。

状态值与原生一致(`pending` / `running` / `done` / `failed`)。

错误码字符串与 `/v1` 接口不同,例如缺少 prompt 在此为 `missing_prompt`,在 `/v1` 为 `invalid_request`。判断错误类别请以 HTTP 状态码为准。

## 两套接口共同的注意点

**鉴权类错误使用通用格式。** `{code,...}` 只用于接口自身的成功与业务错误;Key 无效、余额不足、超出速率限制等由通用中间件返回:

```json
{ "error": { "message": "...", "type": "Unauthorized" } }
```

客户端需要同时处理这两种格式。

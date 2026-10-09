# 真实图像检查与费用记录

日期：2026-10-08。共 20 次真实 65535 / gpt-image-2.5-flare 编辑调用，20 个输出已本地转存；“生成成功”只表示真实返回并存储成功，不表示图像质量通过。以下为工程侧目视检查，**不能替代 PRD 要求的产品人工验收**，未认定 8/10 达标。

## 固定样本与输入

四张真实照片位于 [samples](samples/public-sources.json)：[主图 A](samples/fashion-a.png)、[主图 B](samples/fashion-b.png)、[包](samples/bag.png)、[鞋](samples/shoes.png)。眼镜/大衣参考选自主图照片中的对象。无用户素材时采用公开照片作为技术测试，未公开发布。

10 个固定任务为单对象 3、双对象 3、三对象 2、遮挡难例 2；它们组合自同组四张照片，**不是 10 组独立来源照片**，不能推断广泛分布准确率。选区是事先检查的手动多边形，来源明确标为 manual-polygon，不冒充 AI 自动分割正确。真实悬停分割另由浏览器测试覆盖。

每个 JSON 包含原主图、参考图、Mapping/标签/锚点/Mask ID、实际编译输入/派生图 ID、策略、模型、请求 ID、耗时及输出 ID；对应不可变字节在项目 data/assets。原始照片及输出同时保留在 evidence，完整环境交接需一起复制 data。

## 十例目视观察

| 样本 / 输出 | 实際策略 | 上游 / 总耗时 s | 观察 | 产品人工判定 |
|---|---|---:|---|---|
| [01-single-bag](real/01-single-bag-output-0.png) | full | 35.703 / 39.406 | 包已替换；肩带和围巾附近有变化，精确边界保持不能判通过。 | 待验收 |
| [02-single-shoes](real/02-single-shoes-output-0.png) | context-crop | 34.172 / 37.359 | 红色鞋已替换；原靴筒消失后腿部/袜子被重绘，鞋底和鞋款细节有差异。 | 待验收 |
| [03-single-glasses](real/03-single-glasses-output-0.png) | context-crop | 49.594 / 53.172 | 眼镜区域发生替换；小物件样式/镜腿细节需产品放大判断。 | 待验收 |
| [04-two-bag-shoes](real/04-two-bag-shoes-output-0.png) | context-crop | 52.235 / 55.36 | 包和鞋均出现；鞋款细节及包的位置比例仍需逐项对照。 | 待验收 |
| [05-two-bag-glasses](real/05-two-bag-glasses-output-0.png) | context-crop | 51.062 / 54.406 | 两个区域均变化；眼镜形状与参考不完全一致，不能泛称商品忠实度通过。 | 待验收 |
| [06-two-shoes-glasses](real/06-two-shoes-glasses-output-0.png) | context-crop | 33.203 / 36.782 | 两项可见；鞋和眼镜几何细节仍有差异。 | 待验收 |
| [07-three-a](real/07-three-a-output-0.png) | context-crop | 53.625 / 56.812 | 三项都有修改；包向画面中部移动并变大，目标漂移应作为失败候选保留。 | 待验收 |
| [08-three-b](real/08-three-b-output-0.png) | context-crop | 49.812 / 53.39 | 双手提包及眼镜均变化；提带/手套遮挡残留与商品细节仍需人工评判。 | 待验收 |
| [09-occluded-coat](real/09-occluded-coat-output-0.png) | context-crop | 33.844 / 37.594 | 明显失败：大衣变酒红，但大衣选区外下方蓝色裙装也变深灰；局部保持未通过。 | 待验收 |
| [10-held-bag](real/10-held-bag-output-0.png) | context-crop | 29.781 / 33.0 | 持包区替换完成；握持和遮挡总体可辨，原选区包含成组购物袋，精确轮廓/标识需复核。 | 待验收 |

所有已目视检查输出未发现编号或彩色选区蒙层烧入图像。总体仍有对象位置偏移、源商品细节重绘、目标外变化，不能据此给出产品通过率。请将输出与原图/参考并排放大判断，尤其检查 logo、鞋形、镜框、握持和遮挡。

## 同组路线比较

详见 TECH_RESEARCH 的决策。批量上下文裁剪本次 45.063 秒（1 次请求）；完整图 60.672 秒（1 次）；透明图 63.906 秒（1 次）；串行合计 95.001 秒（2 次）。少量实验无统计显著性结论，裁剪不是所有场景的强制路线。

[批量完整图](real/compare-batch-full-output-0.png) · [批量裁剪](real/compare-batch-context-crop-output-0.png) · [批量透明](real/compare-batch-transparent-output-0.png) · [串行最终](real/compare-serial-2-output-0.png)。串行第二步前中间图尺寸一致，鞋区肉眼仍对齐；最终包也有向中部偏移，故未开放自动串行。

## Mask 与标签实验

| 实验 | 输出与请求 | 观察/限制 |
|---|---|---|
| 原始硬 Mask | [输出](real/mask-hard-output-0.png) / [发送 Mask](real/mask-hard-request-mask.png) | 请求接收并返回图片，不证明像素范围严格约束 |
| 半径 6 px 膨胀 | [输出](real/mask-dilate-output-0.png) / [发送 Mask](real/mask-dilate-request-mask.png) | 保存原始选区；派生 alpha=255-mask；目标外肩带仍变化 |
| 膨胀后 4 px 羽化 | [输出](real/mask-feather-output-0.png) / [发送 Mask](real/mask-feather-request-mask.png) | 有输出，缺严格对照，不能认定模型理解软边或优于硬 Mask |
| 无标签 | [输出](real/label-empty-output-0.png) | 不阻塞生成，包仍被替换；可选标签无需强制填写 |
| 错误标签“红色鞋子” | [输出](real/label-wrong-output-0.png) | 输出仍是黑包，且形状/位置变化；不能宣称标签纠正了选区 |

早期 Mask 实验历史的 compiled.mask_mode 字段遗漏实际请求状态；保留原不可变快照，实际参数见 TECH_RESEARCH 和请求 PNG，不用修改旧历史来掩盖问题。产品默认未启用原生 Mask；恢复原始选区时提示实验参数未启用。

## 全量调用/尺寸/费用记录

编辑响应的 cost_usd 与 usage 全为空；账户模型聚合差分只在两次标签实验周围测得各 +1 请求、+$0.038 USD，见两个 label-*-billing.json。这不是逐请求发票；不能排除同时发生的其他使用。若同价，批量一调用约 $0.038、串行两调用约 $0.076；20 调用约 $0.760 **仅为估算**。模型 price 元数据的 0 不表示免费。未保存账户余额或凭证。

| 请求 | 次数 | 上游 s | 含转存 s | 解码输出 px | 精确请求费用 |
|---|---:|---:|---:|---|---|
| [01-single-bag](real/01-single-bag.json) | 1 | 35.703 | 39.406 | 1024×1536 | 未返回 |
| [02-single-shoes](real/02-single-shoes.json) | 1 | 34.172 | 37.359 | 1024×1536 | 未返回 |
| [03-single-glasses](real/03-single-glasses.json) | 1 | 49.594 | 53.172 | 1024×1536 | 未返回 |
| [04-two-bag-shoes](real/04-two-bag-shoes.json) | 1 | 52.235 | 55.36 | 1024×1536 | 未返回 |
| [05-two-bag-glasses](real/05-two-bag-glasses.json) | 1 | 51.062 | 54.406 | 1024×1536 | 未返回 |
| [06-two-shoes-glasses](real/06-two-shoes-glasses.json) | 1 | 33.203 | 36.782 | 1024×1536 | 未返回 |
| [07-three-a](real/07-three-a.json) | 1 | 53.625 | 56.812 | 1024×1536 | 未返回 |
| [08-three-b](real/08-three-b.json) | 1 | 49.812 | 53.39 | 1536×1024 | 未返回 |
| [09-occluded-coat](real/09-occluded-coat.json) | 1 | 33.844 | 37.594 | 1024×1536 | 未返回 |
| [10-held-bag](real/10-held-bag.json) | 1 | 29.781 | 33.0 | 1536×1024 | 未返回 |
| [compare-batch-context-crop](real/compare-batch-context-crop.json) | 1 | 41.453 | 45.063 | 1024×1536 | 未返回 |
| [compare-batch-full](real/compare-batch-full.json) | 1 | 57.109 | 60.672 | 1024×1536 | 未返回 |
| [compare-batch-transparent](real/compare-batch-transparent.json) | 1 | 60.187 | 63.906 | 1024×1536 | 未返回 |
| [compare-serial-1](real/compare-serial-1.json) | 1 | 52.297 | 55.516 | 1024×1536 | 未返回 |
| [compare-serial-2](real/compare-serial-2.json) | 1 | 36.266 | 39.485 | 1024×1536 | 未返回 |
| [label-empty](real/label-empty.json) | 1 | 48.828 | 53.125 | 1024×1536 | 未返回 |
| [label-wrong](real/label-wrong.json) | 1 | 33.735 | 37.453 | 1024×1536 | 未返回 |
| [mask-dilate](real/mask-dilate.json) | 1 | 49.406 | 52.625 | 1024×1536 | 未返回 |
| [mask-feather](real/mask-feather.json) | 1 | 52.171 | 55.172 | 1024×1536 | 未返回 |
| [mask-hard](real/mask-hard.json) | 1 | 53.5 | 56.937 | 1024×1536 | 未返回 |

## 验收结论

工程接入、真实出图及持久化已经验证；商品忠实度、精确范围保持和 8/10 产品质量门槛尚未通过。失败输出完整保留，未用简单样本替换遮挡难例。没有使用参考原图原样返回冒充生成。

# 配置化权益套餐

权益套餐用于配置一次性购买或订阅周期内的积分、团队人数、并发、排队任务、API 调用额度和存储额度。模型权限、最大分辨率和 4K 不属于套餐权益。

## 套餐层

`benefit_packages` 保存销售配置和有效期规则：

- `purchase_mode`: `one_time` 或 `subscription`。
- `billing_interval`: 订阅的 `month`、`quarter` 或 `year`。
- `validity_mode`: `fixed_days`、`billing_period` 或 `permanent`。
- `activation_policy`: 当前仅支持支付成功立即激活；首次使用和指定时间激活保留为后续扩展字段。
- `stacking_policy`: 禁止重复、顺延有效期或叠加权益。
- `timezone`: 周期发放使用的 IANA 时区，数据库时间仍保存为 UTC。

套餐修改会增加 `version`。已经产生发放记录的套餐不能覆盖编辑，应复制为新编码，避免历史订单引用到新配置。

## 权益项

当前允许的 `resource_type`：

```text
credits
team_seats
image_concurrency
video_concurrency
task_queue_limit
api_quota
storage_quota
```

每个权益项单独配置：

- `amount`: 单次发放数量。
- `grant_mode`: 一次性、按天或按周。
- `grant_count`: 周期发放次数。
- `scope`: 个人或团队。
- `expiry_policy`: 到下一次发放、到套餐结束或永久。
- `aggregation_mode`: 数量相加、取最大值或替换。

## 有效期边界

所有权益使用半开区间：

```text
starts_at <= now < expires_at
```

`expires_at` 到达的瞬间失效。套餐和每次发放都保存自己的开始、结束时间；周期积分不会提前一次性发给用户。

按月订阅使用日历周期。1 月 31 日开始的下一个月周期落在 2 月最后一天，不溢出到 3 月。

## 发放记录

支付完成后，系统按照套餐版本生成 `benefit_grants`。幂等键格式为：

```text
benefit:{order_no}:{package_item_id}:{grant_index}
```

重复支付回调或调度重试只能命中同一条记录，不能重复产生权益。

旧 `recharge_plans` 继续用于兼容已有一次性充值订单，不与新套餐配置混用。

当前 ZPay 接入只支持一次性支付；订阅套餐可以先配置和上架展示，但购买入口会明确标记为“待支付接入”，不会伪装成已经具备自动扣款和续费能力。

## 后台直接开通

管理员可以在“权益套餐”页面对指定用户直接开通套餐，不经过支付。后台开通会创建 `payment_provider=admin` 的已支付订单，并复用同一套套餐版本快照、叠加策略、有效期和按天/按周发放规则；开通原因会写入管理审计日志。团队权益需要目标用户属于目标团队，留空团队 ID 时会尝试使用该用户作为所有者的团队。

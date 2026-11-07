# 原批次内重试与执行容量

失败项的重试保留 `image_tasks.id`、`batch_id`、`created_at`、提示词、参考图和分组信息。成功和执行中的记录保持原状，批次总张数不增加。

`POST /image-tasks/batches/retry` 校验已确认的报价、权限、状态与容量，将选中的失败记录原子地保留为 `pending`，持久化内部受理记录后返回原批次编号。接口不等待外部扣费。相同 `request_id` 重放返回同一受理结果；不同请求不能再次领取同一组待处理记录。

现有持久化批次工作器以单个幂等键扣取整批费用，然后在一个事务内更新原任务、记录逐图积分流水和逐图退款凭据，并转为 `queued`。各图可以有不同价格。新执行使用独立 `task_no`，此前的执行状态、费用、上游追踪和时间保存在受理记录的 `payload.previous_attempts` 中；终态仅清除工作计划，保留审计信息。

明确扣费拒绝、任务创建失败后的成功退款，会恢复原失败记录。未确认的扣费结果持续使用相同幂等键；达到重试上限后保持 `needs_attention`，保留任务和受理信息，不自动另起扣费。原批次的汇总返回 `retry_submission_status` / `retry_submission_error`，内部受理记录不会显示成另一个图片批次。待处理记录只计入一次容量。

历史版本已经创建的独立重试批次保留原记录，不自动合并或删除。旧请求的幂等重放可返回已存在的旧结果。本改动无需数据库迁移。

## Magic 生产执行配置

Magic 应用与数据位于 V3 `/data/workspace/image2`。前端域名的代理位置不改变应用发布目标。发布仍需本地提交并推送，生产 `git pull --ff-only` 后构建 `user-server` 和 `user-web`。

以下现有参数共同设置执行层的 500 个槽位，不改变模型或账户的更小限制：

```dotenv
USER_IMAGE_TASK_GENERATION_THREAD_POOL_SIZE=500
USER_IMAGE_TASK_STORAGE_THREAD_POOL_SIZE=500
USER_IMAGE_TASK_GENERATION_MAX_INFLIGHT=500
USER_IMAGE_TASK_DISPATCHER_BATCH_SIZE=500
USER_IMAGE_TASK_DISPATCHER_MAX_INFLIGHT=500
```

2026-10-13 发布前主机核对：80 CPU、约 128 GB 内存、约 66 GB 可用内存；应用容器没有独立硬内存/CPU配额；相关模型上限为 1000。上线前再次核对主机可用资源，使用现有 Nginx 运行时 drain 阻止新提交，等在途执行和受理完成后替换服务，再取消 drain。

隔离 PostgreSQL 的回归覆盖：长时间排队可被领取、5000 条队列每次只领取实际空闲槽位、250/2000/5000 条重试先受理后一次批量扣费、重复请求、丢失扣费响应、逐次退款、提交失败恢复原任务、原批次卡片和数量不变。重试请求与报价读取上限使用批量生成的 20000 条协议上限，并在受理时校验站点实际批次上限。

`test_image_task_capacity.py` 使用本地替身测试 500 路执行、500 份结果集中到达、数据库开始/完成回调和 500 路存储。每份结果 2 MiB；2026-10-13 本地记录 500 成功、0 失败，约 1.29 秒端到端、P95 1.23 秒、约 1.05 GB 进程峰值 RSS、约 1.39 CPU 秒。替身不调用计费上游，不代表真实模型耗时或更大图片的容量保证；生产只核对实际配置与正常用户请求，不发起额外的收费压测。

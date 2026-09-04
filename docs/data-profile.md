# 数据画像与关联校验

> 生成时间（UTC）：2026-09-01T07:17:00.561272+00:00  
> 原始工作簿：`D:\workspace\tianchi\赛题 1：数据共情者-业务数据.xlsx`  
> SHA-256：`b5ac027e863c5580dab39c8f459e4698d65e9fbec29832c9915448f2087307b7`  
> 读取方式：所有单元格按字符串读取；脚本只读源文件。

## 1. 结论先行

**可以进入第 2 步“评测立标”，但还不能直接宣称模型有效。** 当前快照的消息、订单和工单主键无缺失/重复，113/113 笔订单能关联聊天，80/80 张工单能同时关联聊天和来源订单，足以建立会话级场景评测、风险弱标签规则与黄金案例。限制是：情绪和 P0–P3 没有官方金标签，二级场景存在小样本，图片 29/29 缺失；因此下一步必须先冻结分组切分、人工标注与风险映射规则。

## 2. 数据集、粒度与规模

- 工作表：8 张；业务事实表为聊天、订单和 5 类工单，`数据说明` 不是业务事实表。
- 聊天：138 个会话、998 条消息、112 个买家。
- 订单：113 笔。
- 工单：80 张。
- 场景：一级 10 类、二级 41 类；按会话统计分布，避免长会话被重复加权。

| 表 | 粒度 | 行数 | 列数 | 完全重复行 |
| --- | --- | --- | --- | --- |
| 数据说明 | 说明行（非业务事实表） | 26 | 3 | 8 |
| 聊天记录 | 一行一条消息；message_id 为主键候选 | 998 | 18 | 0 |
| 订单 | 一行一笔订单；订单号为主键候选；当前快照一会话至多一单 | 113 | 19 | 0 |
| 补发换货工单 | 一行一张补发/换货工单；工单号为主键候选 | 24 | 19 | 0 |
| 线下打款工单 | 一行一张线下打款工单；工单号为主键候选 | 13 | 16 | 0 |
| 物流工单 | 一行一张物流工单；工单号为主键候选 | 15 | 17 | 0 |
| 不良反应工单 | 一行一张不良反应工单；工单号为主键候选 | 10 | 19 | 0 |
| 售后退货工单 | 一行一张售后退货工单；工单号为主键候选 | 18 | 16 | 0 |

## 3. 主键、ID 与关联完整性

| 校验 | 状态 | 观测值 |
| --- | --- | --- |
| message_id_unique_not_null | pass | {"rows": 998, "missing": 0, "duplicate_rows": 0} |
| order_id_unique_not_null | pass | {"rows": 113, "missing": 0, "duplicate_rows": 0} |
| ticket_id_unique_not_null | pass | {"rows": 80, "missing": 0, "duplicate_rows": 0} |
| orders_link_to_chat | pass | {"child_distinct": 113, "matched_distinct": 113, "unresolved_distinct": 0, "coverage_rate": 1.0} |
| tickets_link_to_chat | pass | {"child_distinct": 80, "matched_distinct": 80, "unresolved_distinct": 0, "coverage_rate": 1.0} |
| tickets_link_to_orders | pass | {"child_distinct": 80, "matched_distinct": 80, "unresolved_distinct": 0, "coverage_rate": 1.0} |
| chat_order_refs_resolve | pass | {"child_distinct": 113, "matched_distinct": 113, "unresolved_distinct": 0, "coverage_rate": 1.0} |
| chat_ticket_refs_resolve | pass | {"child_distinct": 80, "matched_distinct": 80, "unresolved_distinct": 0, "coverage_rate": 1.0} |
| conversation_message_sequence_unique | pass | {"duplicate_rows": 0} |
| one_order_per_conversation | pass | {"duplicate_rows": 0} |
| one_ticket_per_conversation | pass | {"duplicate_rows": 0} |
| chat_order_refs_match_conversation | pass | {"referencing_rows": 819, "mismatched_rows": 0} |
| chat_ticket_refs_match_conversation | pass | {"referencing_rows": 629, "mismatched_rows": 0} |
| order_payment_time_or_deposit_annotation_valid | pass | {"deposit_annotation_rows": 3, "parse_failures_after_removing_annotation": 0, "deposit_status_mismatches": 0} |
| order_shipping_fields_co_present | pass | {"mismatched_rows": 0, "all_missing_rows": 16} |
| ticket_completion_after_creation | pass | {"parse_failures": 0, "completion_before_creation": 0, "status_completion_mismatches": 0} |
| conversation_scene_labels_consistent | pass | {"inconsistent_conversations": 0} |
| conversation_buyer_consistent | pass | {"inconsistent_conversations": 0} |
| identifier_format_not_float_or_scientific | pass | {"fields_checked": 31, "suspicious_values": 0} |

- 所有 ID 源值均用 `dtype=str` 读取；共检查 31 个标识符字段，未发现 `.0` 浮点尾缀或科学计数法字符串。
- 订单关联聊天：113/113。
- 工单关联聊天：80/80；工单关联来源订单：80/80。

工单构成：

| 工单表 | 行数 |
| --- | --- |
| 补发换货工单 | 24 |
| 线下打款工单 | 13 |
| 物流工单 | 15 |
| 不良反应工单 | 10 |
| 售后退货工单 | 18 |

## 4. 场景标签分布与稀疏性

### 一级场景（按会话）

| scene_major | 会话数 | 占比 |
| --- | --- | --- |
| 产品咨询 | 25 | 18.1% |
| 订单服务 | 22 | 15.9% |
| 补发换货 | 21 | 15.2% |
| 售后退货 | 18 | 13.0% |
| 物流异常 | 15 | 10.9% |
| 退款打款 | 13 | 9.4% |
| 不良反应 | 10 | 7.2% |
| 物流服务 | 8 | 5.8% |
| 会员服务 | 3 | 2.2% |
| 其他服务 | 3 | 2.2% |

### 二级场景（按会话）

| scene_minor | 会话数 | 占比 |
| --- | --- | --- |
| 漏发赠品 | 7 | 5.1% |
| 退款进度查询 | 7 | 5.1% |
| 物流查询 | 5 | 3.6% |
| 错发色号 | 5 | 3.6% |
| 优惠与赠品咨询 | 4 | 2.9% |
| 大促价保补差 | 4 | 2.9% |
| 泛红刺痒 | 4 | 2.9% |
| 七天无理由退货 | 3 | 2.2% |
| 仅退款疑似异常 | 3 | 2.2% |
| 会员权益加赠补发 | 3 | 2.2% |
| 使用不适退货 | 3 | 2.2% |
| 使用方法 | 3 | 2.2% |
| 保价申请被拒 | 3 | 2.2% |
| 催发货 | 3 | 2.2% |
| 包裹少件 | 3 | 2.2% |
| 包裹破损 | 3 | 2.2% |
| 发票申请 | 3 | 2.2% |
| 售后期关闭过敏退款 | 3 | 2.2% |
| 套装搭配推荐 | 3 | 2.2% |
| 好评回访 | 3 | 2.2% |
| 孕妇可用咨询 | 3 | 2.2% |
| 少发正装 | 3 | 2.2% |
| 成分与肤质适配 | 3 | 2.2% |
| 拆封少件拒收 | 3 | 2.2% |
| 拦截改址 | 3 | 2.2% |
| 显示签收未收到 | 3 | 2.2% |
| 正品鉴别咨询 | 3 | 2.2% |
| 比价与决策 | 3 | 2.2% |
| 物流停滞疑似丢件 | 3 | 2.2% |
| 直播间承诺纠纷 | 3 | 2.2% |
| 破损换货 | 3 | 2.2% |
| 积分兑换咨询 | 3 | 2.2% |
| 色号不合适退货 | 3 | 2.2% |
| 色号选择 | 3 | 2.2% |
| 质疑正品退货 | 3 | 2.2% |
| 过敏就医 | 3 | 2.2% |
| 退款迟迟不到账 | 3 | 2.2% |
| 退款金额少退补打 | 3 | 2.2% |
| 退货运费报销 | 3 | 2.2% |
| 闷痘爆痘 | 3 | 2.2% |
| 预售尾款咨询 | 3 | 2.2% |

- 少于 5 个会话的二级类别有 37 个。它们不适合直接做普通随机训练/测试切分后的单类稳定指标；应按会话或买家分组，并在评测方案中合并、定向留出或只做案例级核验。
- `scene_major` / `scene_minor` 只可作为离线标签，不得进入模型输入。

## 5. 缺失、图片与关键字段可用性

- 字段级非空数、非空率和去重数见 [逐表字段字典](field-dictionaries/README.md)。
- 订单的发货时间、快递公司和物流单号各缺 16 条，三个字段逐行共同出现或共同缺失；缺失订单处于交易关闭、预售待付尾款或待发货状态，使用时必须保留“暂未查询到”分支，不能补造物流事实。
- `付款时间` 有 3 条采用“日期时间（定金）”注记；去掉明确注记后均可解析，且都对应“预售-待付尾款”，不应误判为坏日期或完整付款时间。
- 图片路径记录 29 条、唯一路径 29 个；本地存在 0 个，缺失 29 个，存在率 0.0%。当前只能验证缺失降级，不能验证真实图像理解。
- 不良反应工单的症状、是否停用、是否就医字段在当前 10 张工单中均非空，可用于构造风险弱标签；它们仍是 MOCK 消费者自述，不是诊断或病历。
- 完成时间在各类工单中存在业务性缺失，可作为“未闭环”候选信号，不能一概当成脏数据。

## 6. 可评价边界

| 能评 | 暂时不能据此证明 |
| --- | --- |
| 会话级一级/二级场景识别，标签仅作输出对照 | 情绪识别效果：没有现成金标签 |
| 订单/工单事实引用和关联正确率 | P0–P3 风险模型效果：没有官方风险金标签 |
| 不良反应、异常退货、未闭环工单的规则召回 | 真实投诉率、真实客服效率或商业收益 |
| 图片缺失时的降级行为 | 真实多模态图像能力 |

数据切分必须按会话或买家分组；不能按消息随机拆分。任何使用 `scene_major` / `scene_minor` 作为输入的结果都属于标签泄漏。

## 7. 质量问题、风险与处理建议

| 严重度 | 发现 | 影响 | 最小处理 |
| --- | --- | --- | --- |
| 高 | 情绪与风险无金标签 | 无法直接报告可信的情绪/P0–P3 指标 | 人工标注 60–100 个会话；风险规则映射独立冻结并双人复核 |
| 高 | 图片 29/29 缺失 | 无法验证多模态效果 | 只做缺失降级；若后续获得图片，作为新数据版本另行审计 |
| 中 | 二级场景有 37 个类别少于 5 会话 | Macro-F1 方差大、分组切分可能缺类 | 报告支持数；预注册合并/留出策略，不临时挑指标 |
| 中 | MOCK 数据且单店、小样本 | 不能外推真实业务收益 | 所有 PPT/视频结论标注“模拟任务结果” |
| 低 | 业务性缺失（未发货物流、未完成工单） | 若误填会造成事实幻觉 | 保留空值并显式显示“暂未查询到/未完成” |

## 8. 可重复运行

```powershell
$env:PYTHONUTF8='1'
& 'C:\Users\siu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts/profile_data.py --source '赛题 1：数据共情者-业务数据.xlsx' --output-dir 'artifacts/data-profile-20260901' --docs-dir 'docs'
& 'C:\Users\siu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_profile_data -v
```

复跑时用 `profile.json` 中的源文件 SHA-256 判断是否仍是同一快照。若哈希变化，必须生成新的版本目录，不得覆盖或混称旧结果。

## 9. 下一步

冻结第 2 步评测立标：按会话/买家分组建立场景切分；人工标注情绪；把不良反应、异常退货和未闭环工单字段映射成可审计的风险弱标签；选定两个关联完整的黄金案例。

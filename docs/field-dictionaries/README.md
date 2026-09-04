# 逐表字段字典

| 表 | 字典 | 行数 | 列数 | 粒度 |
| --- | --- | --- | --- | --- |
| 数据说明 | [01-data-description.md](01-data-description.md) | 26 | 3 | 说明行（非业务事实表） |
| 聊天记录 | [02-chat-messages.md](02-chat-messages.md) | 998 | 18 | 一行一条消息；message_id 为主键候选 |
| 订单 | [03-orders.md](03-orders.md) | 113 | 19 | 一行一笔订单；订单号为主键候选；当前快照一会话至多一单 |
| 补发换货工单 | [04-replacement-tickets.md](04-replacement-tickets.md) | 24 | 19 | 一行一张补发/换货工单；工单号为主键候选 |
| 线下打款工单 | [05-offline-payment-tickets.md](05-offline-payment-tickets.md) | 13 | 16 | 一行一张线下打款工单；工单号为主键候选 |
| 物流工单 | [06-logistics-tickets.md](06-logistics-tickets.md) | 15 | 17 | 一行一张物流工单；工单号为主键候选 |
| 不良反应工单 | [07-adverse-reaction-tickets.md](07-adverse-reaction-tickets.md) | 10 | 19 | 一行一张不良反应工单；工单号为主键候选 |
| 售后退货工单 | [08-return-tickets.md](08-return-tickets.md) | 18 | 16 | 一行一张售后退货工单；工单号为主键候选 |

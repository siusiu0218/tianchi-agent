# 第一版开源借鉴记录

核验日期：2026-09-15。官方仓库下载到被 Git 忽略的 `.scratch/`，用于只读检查，没有运行其安装脚本或复制其业务代码。

| 来源与固定版本 | 检查的代码 | 本项目适配 |
| --- | --- | --- |
| [RTY798/ai-customer-service-agent](https://github.com/RTY798/ai-customer-service-agent/tree/9a7888023b5bc64b9bf0ca78ce9e94dc750aec42) | `backend/app/data/base.py`、`agents/graph.py`、`agents/llm_client.py` | 借鉴 Provider 分离、查询后汇总、兼容 HTTP 模型接口的组织方式。独立实现 `ExcelProvider`，改为只读比赛数据和确定性顺序流程，未引入其五 Agent 和知识库依赖。 |
| [gaurav-oberoi/support-agent-hitl](https://github.com/gaurav-oberoi/support-agent-hitl/tree/66df5851249aa23ece37609ee1c856580fa2dcbd) | `app/nodes.py`、README | 借鉴高风险动作需人工控制、模型可替换以便离线测试的原则。本轮只提供草稿，不实现退款执行，也不声称已完成 LangGraph 暂停/恢复审批。 |

RTY 仓库 README 声明 MIT，但此固定版本根目录未发现独立 LICENSE 文件。本轮不复制代码；后续若复用源代码，应先核实完整许可与版权声明。HITL README 声明 MIT；本轮同样仅借鉴结构。

本项目新增逻辑：回放时点过滤、快照与历史信息分离、离线标签排除、买家原文证据、规则优先级、模型受约束措辞选择、缺图提示。开源项目自报的准确率、测试数和生产能力不转用为本项目结果。

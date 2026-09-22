# 共情副驾桌面版

## 0.3.1 修复

修复点击左侧会话时出现空白独立窗口的问题：订单详情组件在显示前即绑定到主界面。新增真实点击切换与折叠面板的窗口事件回归测试，连续切换 20 次不出现额外窗口；全部 42 项测试通过。

## 0.3 界面更新

- 深色窄侧边导航，分别进入会话、风险看板和模型设置。
- 会话列表显示编号、消息摘要与历史日期，支持全文搜索。
- 原生左右消息气泡：客户在左、客服在右，短句随文字收缩，长句自动换行；保留完整历史和最新消息定位。
- 风险原文、订单和业务快照分组显示，详细记录可以展开或折叠。
- 回复编辑、审核弹窗、任务统计卡片、处理时间线和审核历史使用统一样式。

设计调研参考 [Chatwoot](https://github.com/chatwoot/chatwoot)、[RoomKit UI](https://github.com/roomkit-live/roomkit-ui) 和 [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)。本轮控件、主题和线条图标在现有 PySide6 上自行实现，未引入这些项目的运行依赖或复制其品牌素材。

本轮源码回归：41 项通过，含 9 项桌面交互测试。界面截图覆盖两个会话、窄窗口、任务看板、审核弹窗和任务详情，均使用临时记录库。

## 打开软件

- 安装版：双击 `release/desktop/EmpathyCopilot-Setup.exe`，按向导完成安装，再打开桌面上的“共情副驾”。
- 便携版：打开 `release/desktop/EmpathyCopilot/EmpathyCopilot.exe`。必须保留旁边的 `_internal` 文件夹，不可只复制 EXE。
- 首次打开点击右上角“选择 Excel”，选择项目中的 `赛题 1：数据共情者-业务数据.xlsx`。文件路径会记住，下次直接加载。

安装包不含比赛 Excel、项目 `.env`、API Key 或已有业务记录。向队友提供业务文件时另行交接。

## 使用

1. 左侧按会话编号或聊天文字搜索；中间显示完整历史，默认定位到最新消息。
2. 右侧查看风险原文、订单、截至聊天结束已创建的工单和另行标注的工作簿快照。
3. 回复区默认生成本地模板，可以编辑。点击“确认并保存”，填写操作人、负责人和原因，核对后勾选确认。
4. “风险看板”展示确认后的本地任务。选中任务，点击“查看 / 处理选中任务”推进状态、分派负责人或查看时间线。
5. “模型设置”填写接口地址、模型和 API Key。点击“生成模型建议”可预览发送内容。API Key 仅保留在本次运行内；模型目前只选择开场措辞，不自由生成业务事实。

离线时可读取 Excel、生成模板、审核和处理本地任务；调用远程模型时需要网络。保存不等于向客户发送，未连接真实客服渠道。

## 数据保存位置

- 设置：`%LOCALAPPDATA%\EmpathyCopilot\settings.json`
- 审核与任务：`%LOCALAPPDATA%\EmpathyCopilot\reviews.sqlite3`

桌面版有独立记录库，不会自动导入旧网页版审核记录。升级覆盖程序或卸载软件不会主动删除上述用户数据。备份时请先退出程序再复制此目录。

## 源码运行与构建

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.venv\Scripts\python.exe -m desktop
.venv\Scripts\python.exe -m unittest discover -s tests -p test_desktop.py -v
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

构建安装包需要 Inno Setup 6。构建只收集桌面入口及其依赖，不包含 Streamlit 页面。
`--data` 和 `--state` 可指定工作簿与独立记录库；`--smoke-test` 自动打开再退出用于启动验证。

## 验证边界

2026-09-17 本机验收：38 项测试通过（32 项原有测试、6 项桌面交互测试）；便携 EXE 和安装后 EXE 均在项目目录之外成功加载工作簿并正常退出；安装程序退出码为 0，桌面快捷方式目标已核实，安装前后主程序哈希一致。修复了构建时误收集其他应用 ICU DLL 的问题，构建脚本现在使用受限的依赖搜索路径。

桌面测试使用临时记录库和模拟模型返回，不发送真实模型请求。模型辅助的真实服务效果需要用户自行配置后检验。
这是 Windows x64 构建；未在 macOS、Linux 或另一台干净 Windows 机器上验收。安装包未做发布者数字签名。

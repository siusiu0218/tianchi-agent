"""Shared model connection dialog for the workbench and simulation window."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QFileDialog, QMessageBox, QDialogButtonBox
from desktop.config import save_settings

def configure_model(self):
    from desktop.window import label, button
    dialog = QDialog(self)
    dialog.setWindowTitle("模型连接设置")
    dialog.resize(560, 310)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(16)
    layout.addWidget(label("连接你的 AI 副驾", "pageTitle"))
    layout.addWidget(label("用于服务摘要和回复建议。已选择的 .env 会在启动时自动读取；密钥不会复制到设置文件。使用 AI 功能时会向接口发送遮蔽后的会话和必要参考信息。", "muted"))
    form = QFormLayout()
    base = QLineEdit(self.settings.get("base_url", ""))
    base.setPlaceholderText("https://…/v1")
    model = QLineEdit(self.settings.get("model", ""))
    key = QLineEdit(self.api_key)
    key.setEchoMode(QLineEdit.EchoMode.Password)
    for name, field in [("接口地址", base), ("模型名称", model), ("API Key", key)]:
        form.addRow(name, field)
    layout.addLayout(form)
    env_path = self.settings.get('env_path', '')
    def import_config():
        nonlocal env_path
        from dotenv import dotenv_values
        path, _ = QFileDialog.getOpenFileName(dialog, '读取已有模型配置', '', '环境配置 (*.env);;所有文件 (*)')
        if not path:
            return
        try:
            values = dotenv_values(path, interpolate=False)
            base.setText(values.get('LLM_BASE_URL') or '')
            model.setText(values.get('LLM_MODEL') or '')
            key.setText(values.get('LLM_API_KEY') or '')
            env_path = path
        except (OSError, ValueError):
            QMessageBox.warning(dialog, '读取失败', '请检查配置文件格式和权限。')
    layout.addWidget(button('选择 .env 配置（下次启动自动读取）', import_config))
    controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    controls.accepted.connect(dialog.accept)
    controls.rejected.connect(dialog.reject)
    layout.addWidget(controls)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        settings = dict(self.settings, base_url=base.text().strip(), model=model.text().strip(), env_path=env_path)
        save_settings(settings, self.settings_directory)
        self.settings, self.api_key = settings, key.text()

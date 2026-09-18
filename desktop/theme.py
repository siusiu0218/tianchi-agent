"""Shared visual tokens for the native workbench."""

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #243247; }
QMainWindow, QDialog { background: #f5f7fb; }
QWidget#surface, QFrame#surface { background: white; border: 1px solid #e4e9f1; border-radius: 12px; }
QWidget#rail { background: #172438; border-radius: 0; }
QLabel#railBrand { color: white; background: #5874ed; border-radius: 12px; font-size: 22px; font-weight: 700; }
QToolButton#nav { background: transparent; border: none; color: #9caec6; padding: 7px 3px; border-radius: 10px; font-size: 11px; }
QToolButton#nav:hover { background: #24334b; color: white; }
QToolButton#nav:checked { background: #304463; color: white; }
QLabel#heading { font-size: 17px; font-weight: 600; color: #202e43; }
QLabel#pageTitle { font-size: 22px; font-weight: 700; }
QLabel#muted { color: #8190a5; font-size: 11px; }
QLabel#section { color: #7e8da4; font-size: 11px; font-weight: 600; }
QLabel#error { color: #bc4860; }
QLabel#pill { color: #5572bd; background: #eff3ff; border-radius: 9px; padding: 4px 9px; font-size: 11px; }
QLabel#avatar { color: #567298; background: #e8eff9; border-radius: 12px; font-weight: 600; }
QLabel#agentAvatar { color: white; background: #627bec; border-radius: 12px; font-weight: 600; }
QLabel#date { color: #8996a9; font-size: 10px; background: #edf1f7; border-radius: 9px; padding: 4px 12px; }
QFrame#bubbleIn { background: white; border: 1px solid #e3e9f1; border-radius: 13px; }
QFrame#bubbleOut { background: #e9edff; border: 1px solid #dfe5fc; border-radius: 13px; }
QLabel#message { font-size: 13px; color: #2a3850; background: transparent; }
QLabel#messageMeta { color: #8b98ad; font-size: 10px; background: transparent; }
QFrame#riskCard { background: #fff3f3; border: 1px solid #f7dfe3; border-radius: 10px; }
QFrame#summaryCard { background: #f4f7ff; border: 1px solid #e0e7f7; border-radius: 10px; }
QFrame#serviceCard { background: #fff8eb; border: 1px solid #f1e5c9; border-radius: 10px; }
QLabel#riskTitle { color: #bc4860; font-size: 16px; font-weight: 700; }
QLabel#serviceTitle { color: #aa7a31; font-size: 16px; font-weight: 700; }
QFrame#quote { background: #f6f8fc; border: 0; border-left: 3px solid #b5c4ee; border-radius: 5px; }
QFrame#metric { background: white; border: 1px solid #e4e9f1; border-radius: 12px; }
QLabel#metricNumber { font-size: 30px; font-weight: 700; }
QLineEdit, QComboBox, QSpinBox { background: #f8faff; border: 1px solid #e3e9f2; border-radius: 7px; padding: 8px 10px; min-height: 18px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #93a6ed; background: white; }
QTextEdit, QTextBrowser { background: white; border: 1px solid #e3e9f2; border-radius: 9px; padding: 10px; selection-background-color: #dfe6ff; }
QTextEdit#draft { border: none; padding: 2px; background: transparent; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border: none; padding: 0; }
QPushButton { background: white; border: 1px solid #dde4ee; border-radius: 7px; padding: 8px 13px; font-size: 12px; }
QPushButton:hover { background: #f0f4fd; border-color: #bccaf0; }
QPushButton#primary { background: #5873df; border: 1px solid #5873df; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #4963cf; }
QPushButton#quiet { background: transparent; border: none; color: #778aa6; padding: 5px; }
QPushButton#quiet:hover { color: #526ecd; background: #f0f4fc; }
QPushButton#fold { background: transparent; border: none; border-top: 1px solid #edf0f6; border-radius: 0; padding: 12px 0; text-align: left; font-weight: 600; }
QPushButton:disabled { background: #edf0f5; color: #a0abba; border-color: #e7ebf2; }
QCheckBox { padding: 7px 0; }
QCheckBox::indicator { width: 17px; height: 17px; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 10px 20px; background: #edf1f8; border-radius: 5px; margin-right: 4px; }
QTabBar::tab:selected { color: #5873df; background: white; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #ccd5e4; min-height: 32px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #aebdd2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: transparent; width: 9px; height: 8px; }
QStatusBar { background: #f5f7fb; color: #8a96a8; font-size: 10px; border-top: 1px solid #e8edf4; }
QToolTip { background: #24334b; color: white; border: none; padding: 5px; }
"""

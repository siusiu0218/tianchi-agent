"""Shared visual tokens for the native workbench."""

from pathlib import Path
import re

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 14px; font-weight: 400; color: #263244; }
QMainWindow, QDialog { background: #faf9f7; }
QWidget#surface, QFrame#surface { background: white; border: 1px solid #e6e5ea; border-radius: 12px; }
QWidget#rail { background: #f0eff4; border-radius: 0; }
QLabel#railStatus { color: #5968b8; font-size: 11px; padding: 4px 0; }
QLabel#railBrand { color: white; background: #5968d9; border-radius: 12px; font-size: 22px; font-weight: 700; }
QToolButton#nav { background: transparent; border: none; color: #596174; padding: 7px 3px; border-radius: 10px; font-size: 12px; }
QToolButton#nav:hover { background: #e4e3ef; color: #263244; }
QToolButton#nav:checked { background: #dfdff1; color: #3947a3; }
QLabel#heading { font-size: 16px; font-weight: 600; color: #263244; }
QLabel#pageTitle { font-size: 20px; font-weight: 600; }
QLabel#muted { color: #626d7c; font-size: 12px; }
QLabel#section { color: #626d7c; font-size: 14px; font-weight: 600; }
QLabel#summaryHeading { color: #263244; font-size: 16px; font-weight: 600; margin-top: 5px; }
QLabel#summaryBody, QTextBrowser#summaryBody { color: #263244; font-size: 14px; }
QTextBrowser#message, QTextBrowser#summaryBody { border: none; padding: 0; margin: 0; background: transparent; }
QLabel#summaryRisk { color: #b83f50; background: #fff1f2; border-radius: 6px; padding: 8px; font-size: 12px; font-weight: 600; }
QPushButton#summaryAction { font-size: 14px; padding: 5px 10px; }
QLabel#error { color: #b83f50; }
QLabel#riskBadge { color: #626d7c; background: #f0eff4; border-radius: 6px; padding: 6px 10px; font-size: 12px; }
QLabel#riskBadge[level="P0"] { color: #b83f50; background: #fff1f2; border: 1px solid #f1ccd3; font-weight: 600; }
QPushButton:focus, QToolButton:focus { border: 1px solid #5968d9; }
QTextEdit:focus { border: 1px solid #5968d9; }
QLabel#pill { color: #4c5bbb; background: #efeffb; border-radius: 9px; padding: 4px 9px; font-size: 12px; }
QLabel#avatar { color: #566177; background: #eeedf5; border-radius: 12px; font-weight: 600; }
QLabel#agentAvatar { color: white; background: #5968d9; border-radius: 12px; font-weight: 600; }
QLabel#date { color: #626d7c; font-size: 12px; background: #efedf1; border-radius: 9px; padding: 4px 12px; }
QFrame#bubbleIn { background: white; border: 1px solid #e8e6eb; border-radius: 13px; }
QFrame#bubbleOut { background: #efeffb; border: 1px solid #e3e3f4; border-radius: 13px; }
QFrame#bubbleIn[located="true"], QFrame#bubbleOut[located="true"] { background: #eeeafd; border: 1px solid #8991de; }
QToolButton#panelToggle { border: none; border-radius: 8px; background: transparent; padding: 5px; }
QToolButton#panelToggle:hover, QToolButton#panelToggle:checked { background: #eeedf5; }
QToolButton#panelToggle:focus { border: 1px solid #8991de; }
QLineEdit#inboxSearch { background: #f5f5f5; border: 1px solid transparent; border-radius: 18px; padding: 7px 4px; min-height: 20px; color: #333333; }
QLineEdit#inboxSearch:focus { border-color: #c7cbea; }
QToolButton#inboxAction { border: none; border-radius: 18px; padding: 7px; background: #f5f5f5; }
QToolButton#inboxAction:hover, QToolButton#inboxAction:checked, QToolButton#inboxAction[active="true"] { background: #eeedf8; }
QToolButton#inboxAction:focus { border: 1px solid #8991de; }
QToolButton#inboxAction::menu-indicator { image: none; width: 0; }
QMenu { background: white; border: 1px solid #e4e4ee; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 18px; border-radius: 6px; }
QMenu::item:selected { background: #eeedf8; color: #4753b7; }
QMenu#inboxMenu { background: white; border: 1px solid #e8e8e8; border-radius: 10px; padding: 6px; }
QMenu#inboxMenu::item { padding: 10px 40px 10px 12px; border-radius: 6px; color: #262626; }
QMenu#inboxMenu::item:checked, QMenu#inboxMenu::item:selected { background: #f5f5f5; color: #262626; }
QMenu#inboxMenu::indicator { width: 0; height: 0; image: none; }
QMenu#inboxMenu::separator { height: 1px; background: #eeeeee; margin: 5px 0; }
QSplitter#inboxSplit::handle { background: transparent; }
QListWidget#messageMap { padding-top: 12px; }
QLabel#message, QTextBrowser#message { font-size: 15px; font-weight: 400; color: #202124; background: transparent; }
QLabel#messageMeta { color: #626d7c; font-size: 12px; background: transparent; }
QFrame#riskCard { background: #fff3f3; border: 1px solid #f7dfe3; border-radius: 10px; }
QFrame#summaryCard { background: #f4f7ff; border: 1px solid #e0e7f7; border-radius: 10px; }
QFrame#serviceCard { background: #fff8eb; border: 1px solid #f1e5c9; border-radius: 10px; }
QLabel#riskTitle { color: #b83f50; font-size: 16px; font-weight: 600; }
QLabel#serviceTitle { color: #aa7a31; font-size: 16px; font-weight: 600; }
QFrame#quote { background: #f6f8fc; border: 0; border-left: 3px solid #b5c4ee; border-radius: 5px; }
QFrame#metric { background: white; border: 1px solid #e6e5ea; border-radius: 12px; }
QLabel#metricNumber { font-size: 30px; font-weight: 700; }
QLineEdit, QComboBox, QSpinBox { background: #fcfbfd; border: 1px solid #dcdce5; border-radius: 8px; padding: 8px 10px; min-height: 18px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #5968d9; background: white; }
QComboBox, QSpinBox { background: #f6f6fa; border: 1px solid #e7e7ef; border-radius: 10px; padding: 8px 34px 8px 12px; }
QComboBox:hover, QSpinBox:hover { background: #f0f0f8; border-color: #c9cbe2; }
QComboBox { combobox-popup: 0; }
QComboBox:on { background: #efeffb; border-color: #8991de; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border: none; background: transparent; }
QComboBox::down-arrow { image: url(@ASSETS@/chevron-down.svg); width: 14px; height: 14px; }
QWidget#selectPopup { background: transparent; border: none; }
QListView#selectOptions { background: #ffffff; border: 1px solid #e4e4ee; border-radius: 12px; padding: 6px; outline: none; }
QListView#selectOptions::item { min-height: 24px; padding: 6px 10px; border: none; border-radius: 7px; color: #465268; }
QListView#selectOptions::item:hover { background: #f4f4fa; }
QListView#selectOptions::item:selected { background: #ededfb; color: #4753b7; }
QSpinBox::up-button { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: none; border-top-right-radius: 9px; background: transparent; }
QSpinBox::down-button { subcontrol-origin: padding; subcontrol-position: bottom right; width: 28px; border: none; border-bottom-right-radius: 9px; background: transparent; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e6e7f5; }
QSpinBox::up-arrow { image: url(@ASSETS@/plus.svg); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url(@ASSETS@/minus.svg); width: 12px; height: 12px; }
QTextEdit, QTextBrowser { background: white; border: 1px solid #dcdce5; border-radius: 9px; padding: 10px; selection-background-color: #dfe6ff; }
QTextEdit#draft { border: none; padding: 2px; background: transparent; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border: none; padding: 0; }
QListWidget#reportMessages::item { color: #263244; }
QListWidget#reportMessages::item:hover { background: #eef1fb; color: #263244; }
QListWidget#reportMessages::item:selected { background: #dfe6ff; color: #263244; }
QListWidget#reportMessages::indicator { width: 18px; height: 18px; }
QListWidget#reportMessages::indicator:unchecked { image: url(@ASSETS@/report-unchecked.svg); }
QListWidget#reportMessages::indicator:checked { image: url(@ASSETS@/report-checked.svg); }
QWidget#reportMessageRow { background: transparent; border: none; }
QWidget#reportMessageRow[reportedSelected="true"] { background: #e5e7f0; }
QCheckBox#reportPick { padding: 0; background: transparent; }
QCheckBox#reportPick::indicator { width: 20px; height: 20px; }
QCheckBox#reportPick::indicator:unchecked { image: url(@ASSETS@/report-unchecked.svg); }
QCheckBox#reportPick::indicator:checked { image: url(@ASSETS@/report-checked.svg); }
QPushButton { background: white; border: 1px solid #dcdce5; border-radius: 8px; padding: 8px 13px; font-size: 14px; }
QPushButton:hover { background: #f0f4fd; border-color: #bccaf0; }
QPushButton:checked { background: #efeffb; border-color: #5968d9; color: #3947a3; }
QPushButton#primary { background: #5968d9; border: 1px solid #5968d9; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #4756c1; }
QPushButton#quiet { background: transparent; border: none; color: #626d7c; padding: 5px; }
QPushButton#quiet:hover { color: #4c5bbb; background: #f0f4fc; }
QPushButton#fold { background: transparent; border: none; border-top: 1px solid #edf0f6; border-radius: 0; padding: 12px 0; text-align: left; font-weight: 600; }
QPushButton:disabled { background: #edf0f5; color: #a0abba; border-color: #e7ebf2; }
QCheckBox { padding: 7px 0; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox#checklistDone::indicator:unchecked { background: white; border: 1px solid #9eabc2; border-radius: 3px; }
QToolButton#checklistMenu { background: transparent; border: none; padding: 2px; }
QToolButton#checklistMenu::menu-indicator { image: none; width: 0px; }
QToolButton#evidenceButton { background: transparent; border: none; border-radius: 5px; padding: 2px; }
QToolButton#evidenceButton:hover { background: #e8efff; }
QPushButton#checklistAdd, QPushButton#checklistFile { background: transparent; border: none; color: #4c5bbb; text-align: left; padding: 3px 0; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 10px 20px; background: #edf1f8; border-radius: 5px; margin-right: 4px; }
QTabBar::tab:selected { color: #5968d9; background: white; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #ccd5e4; min-height: 32px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #aebdd2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: transparent; width: 9px; height: 8px; }
QStatusBar { background: #faf9f7; color: #626d7c; font-size: 12px; border-top: 1px solid #e8edf4; }
QToolTip { background: white; color: #465268; border: 1px solid #e4e4ee; border-radius: 8px; padding: 10px; }
"""
STYLE = STYLE.replace("@ASSETS@", (Path(__file__).parent / "assets").as_posix())


def scaled_style(percent):
    """Scale stylesheet dimensions from the original tokens, without cumulative rounding."""
    factor = percent / 100
    return re.sub(r"(\d+(?:\.\d+)?)px\b",
                  lambda match: f"{max(1, round(float(match.group(1)) * factor))}px", STYLE)

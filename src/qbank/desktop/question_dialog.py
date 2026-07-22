"""Compact, validated question creation and copy dialogs for Studio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from qbank.models import ID_PATTERN
from qbank.presentation.studio.design.metrics import METRICS

QuestionDialogMode = Literal["new", "copy"]


@dataclass(frozen=True)
class QuestionIdentity:
    """Validated values returned by a question identity dialog."""

    question_id: str
    title: str | None = None


class QuestionIdentityForm(QWidget):
    """Reusable question identity fields shown in dialogs and the gallery."""

    validity_changed = Signal(bool)

    def __init__(
        self,
        mode: QuestionDialogMode,
        default_subject: str,
        default_language: str,
        source: tuple[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.default_subject = default_subject
        self.default_language = default_language
        self.source = source
        self.id_input = QLineEdit()
        self.id_input.setAccessibleName("题目 ID")
        self.id_input.setPlaceholderText("例如：OPT-INT-0002")
        self.id_input.setMaxLength(80)
        self.title_input = QLineEdit()
        self.title_input.setAccessibleName("题目标题")
        self.title_input.setPlaceholderText("简明描述题目考查内容")
        self.title_input.setMaxLength(200)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setObjectName("fieldHint")
        self.target = QLabel()
        self.target.setWordWrap(True)
        self.target.setObjectName("fieldHint")
        self._build_layout()
        self.id_input.textChanged.connect(self._update_state)
        self.title_input.textChanged.connect(self._update_state)
        self._update_state()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_2)
        if self.mode == "copy" and self.source is not None:
            source_id, source_title = self.source
            source = QLabel(f"复制来源：{source_title}\n{source_id}")
            source.setWordWrap(True)
            source.setObjectName("inspectorSectionLabel")
            layout.addWidget(source)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(METRICS.space_3)
        form.setVerticalSpacing(METRICS.space_2)
        form.addRow("题目 ID", self.id_input)
        if self.mode == "new":
            form.addRow("标题", self.title_input)
        layout.addLayout(form)
        layout.addWidget(self.feedback)
        layout.addWidget(self.target)

    def is_valid(self) -> bool:
        """Return whether the visible fields form a valid submission."""
        valid_id = re.fullmatch(ID_PATTERN, self.id_input.text().strip()) is not None
        valid_title = self.mode == "copy" or bool(self.title_input.text().strip())
        return valid_id and valid_title

    def values(self) -> QuestionIdentity:
        """Return normalized form values after validation."""
        title = self.title_input.text().strip() if self.mode == "new" else None
        return QuestionIdentity(self.id_input.text().strip(), title)

    def _update_state(self, *_: object) -> None:
        question_id = self.id_input.text().strip()
        valid_id = re.fullmatch(ID_PATTERN, question_id) is not None
        if question_id and not valid_id:
            self.feedback.setText("ID 必须使用大写字母、数字和连字符，例如 OPT-INT-0002。")
            self.feedback.setObjectName("statusError")
        else:
            self.feedback.setText(
                "新题将以草稿、其他题型、难度 1 创建；创建后可在题目详情中继续补充。"
                if self.mode == "new"
                else "副本会获得新 ID，并自动回到草稿状态；原题不会被修改。"
            )
            self.feedback.setObjectName("fieldHint")
        target_id = question_id or "<题目 ID>"
        self.target.setText(
            f"目标：questions/{self.default_subject}/{target_id}.md · 语言 {self.default_language}"
        )
        self.feedback.style().unpolish(self.feedback)
        self.feedback.style().polish(self.feedback)
        self.validity_changed.emit(self.is_valid())


class QuestionIdentityDialog(QDialog):
    """Native Studio dialog that gathers all question identity fields once."""

    def __init__(
        self,
        mode: QuestionDialogMode,
        default_subject: str,
        default_language: str,
        source: tuple[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建题目" if mode == "new" else "复制题目")
        self.setAccessibleName(self.windowTitle())
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_4,
            METRICS.space_4,
            METRICS.space_4,
            METRICS.space_4,
        )
        layout.setSpacing(METRICS.space_3)
        self.form = QuestionIdentityForm(
            mode,
            default_subject,
            default_language,
            source,
            self,
        )
        layout.addWidget(self.form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.accept_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.accept_button.setText("创建" if mode == "new" else "复制")
        self.accept_button.setAccessibleName(self.accept_button.text())
        self.accept_button.setDefault(True)
        self.cancel_button.setText("取消")
        self.cancel_button.setAccessibleName("取消")
        self.accept_button.setEnabled(self.form.is_valid())
        self.form.validity_changed.connect(self.accept_button.setEnabled)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.form.id_input.setFocus()

    @classmethod
    def get_new_question(
        cls,
        parent: QWidget,
        default_subject: str,
        default_language: str,
    ) -> QuestionIdentity | None:
        """Collect a new question ID and title in one validated dialog."""
        dialog = cls("new", default_subject, default_language, parent=parent)
        return dialog.form.values() if dialog.exec() == QDialog.DialogCode.Accepted else None

    @classmethod
    def get_question_copy(
        cls,
        parent: QWidget,
        default_subject: str,
        default_language: str,
        source: tuple[str, str],
    ) -> QuestionIdentity | None:
        """Collect the destination ID for an explicit question copy."""
        dialog = cls("copy", default_subject, default_language, source, parent)
        return dialog.form.values() if dialog.exec() == QDialog.DialogCode.Accepted else None

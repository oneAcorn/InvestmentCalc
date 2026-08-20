"""PySide6 主界面。"""
from __future__ import annotations

import os
import sys
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenuBar, QMessageBox,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from .calc import InvestmentStats, PortfolioStats
from .excel_io import export_to_excel, import_from_excel
from .models import (
    CURRENCIES, DEFAULT_FX, INVESTMENT_TYPES, MONEY_IN, TRANSACTION_TYPES,
    Portfolio, Investment, Transaction,
)

APP_TITLE = "投资年化收益计算 (XIRR / TWRR)"


def _fmt_pct(v, nd=2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:,.{nd}f}%"


def _fmt_num(v, nd=2) -> str:
    return f"{v:,.{nd}f}"


def _pct_color(v) -> str:
    if v is None:
        return "#666666"
    return "#c0392b" if v >= 0 else "#2e7d32"


class TransactionDialog(QDialog):
    def __init__(self, parent, currency: str, tx: Transaction | None = None):
        super().__init__(parent)
        self.setWindowTitle("编辑交易" if tx else "添加交易")
        self.setMinimumWidth(420)
        self.currency = currency

        grid = QGridLayout(self)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        grid.addWidget(QLabel("日期"), 0, 0)
        grid.addWidget(self.date_edit, 0, 1, 1, 3)

        self.type_combo = QComboBox()
        self.type_combo.addItems(TRANSACTION_TYPES)
        grid.addWidget(QLabel("类型"), 1, 0)
        grid.addWidget(self.type_combo, 1, 1, 1, 3)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.0, 1e15)
        self.amount_spin.setDecimals(4)
        grid.addWidget(QLabel("金额(条目币种)"), 2, 0)
        grid.addWidget(self.amount_spin, 2, 1, 1, 3)

        self.fx_spin = QDoubleSpinBox()
        self.fx_spin.setRange(0.0001, 100000.0)
        self.fx_spin.setDecimals(4)
        self.fx_spin.setValue(DEFAULT_FX.get(currency, 1.0))
        self.fx_label = QLabel("汇率(→人民币)")
        self.fx_label.setEnabled(currency != "CNY")
        self.fx_spin.setEnabled(currency != "CNY")
        grid.addWidget(self.fx_label, 3, 0)
        grid.addWidget(self.fx_spin, 3, 1, 1, 3)

        self.val_check = QCheckBox("记录当日整仓市值(用于精确TWRR)")
        self.val_spin = QDoubleSpinBox()
        self.val_spin.setRange(0.0, 1e15)
        self.val_spin.setDecimals(4)
        self.val_spin.setEnabled(False)
        self.val_check.toggled.connect(self.val_spin.setEnabled)
        grid.addWidget(self.val_check, 4, 0, 1, 4)
        grid.addWidget(self.val_spin, 5, 1, 1, 3)

        self.note_edit = QLineEdit()
        grid.addWidget(QLabel("备注"), 6, 0)
        grid.addWidget(self.note_edit, 6, 1, 1, 3)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, 7, 0, 1, 4)

        if tx is not None:
            self.date_edit.setDate(QDate(tx.date.year, tx.date.month, tx.date.day))
            self.type_combo.setCurrentText(tx.type)
            self.amount_spin.setValue(tx.amount)
            self.fx_spin.setValue(tx.fx)
            if tx.holding_value is not None:
                self.val_check.setChecked(True)
                self.val_spin.setValue(tx.holding_value)
            self.note_edit.setText(tx.note)

    def result_tx(self) -> Transaction:
        d = self.date_edit.date()
        return Transaction(
            date=date(d.year(), d.month(), d.day()),
            type=self.type_combo.currentText(),
            amount=self.amount_spin.value(),
            fx=self.fx_spin.value(),
            holding_value=self.val_spin.value() if self.val_check.isChecked() else None,
            note=self.note_edit.text().strip(),
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 720)
        self.portfolio = Portfolio()
        self.data_path = None
        self._loading = False

        self._build_ui()
        self._load_initial_data()
        self.refresh()

    # ------------------------------------------------------------ UI 构建
    def _build_ui(self):
        menu = self.menuBar()
        fm = menu.addMenu("文件")
        fm.addAction("打开数据…", self.open_json)
        fm.addAction("另存数据…", self.save_json_as)
        fm.addSeparator()
        fm.addAction("退出", self.close)

        tm = menu.addMenu("工具")
        tm.addAction("导出 Excel…", self.export_excel)
        tm.addAction("导入 Excel…", self.import_excel)

        hm = menu.addMenu("帮助")
        hm.addAction("使用说明", self.show_about)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([300, 800])
        self.setCentralWidget(splitter)

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("投资条目"))
        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._on_select)
        lay.addWidget(self.list_widget)

        row = QHBoxLayout()
        btn_new = QPushButton("新建")
        btn_del = QPushButton("删除")
        btn_new.clicked.connect(self.add_investment)
        btn_del.clicked.connect(self.delete_investment)
        row.addWidget(btn_new)
        row.addWidget(btn_del)
        lay.addLayout(row)
        return w

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "background:#f4f6f8;border:1px solid #d0d0d0;padding:8px;border-radius:4px;")
        lay.addWidget(self.summary_label)

        form = QGridLayout()
        form.addWidget(QLabel("名称"), 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._commit_name)
        form.addWidget(self.name_edit, 0, 1)

        form.addWidget(QLabel("类型"), 0, 2)
        self.itype_combo = QComboBox()
        self.itype_combo.addItems(INVESTMENT_TYPES)
        self.itype_combo.currentIndexChanged.connect(self._commit_itype)
        form.addWidget(self.itype_combo, 0, 3)

        form.addWidget(QLabel("币种"), 1, 0)
        self.currency_combo = QComboBox()
        self.currency_combo.addItems(CURRENCIES)
        self.currency_combo.currentIndexChanged.connect(self._commit_currency)
        form.addWidget(self.currency_combo, 1, 1)

        form.addWidget(QLabel("当前市值(条目币种)"), 1, 2)
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.0, 1e15)
        self.value_spin.setDecimals(2)
        self.value_spin.valueChanged.connect(self._commit_value)
        form.addWidget(self.value_spin, 1, 3)

        form.addWidget(QLabel("当前汇率(→人民币)"), 2, 0)
        self.fx_spin = QDoubleSpinBox()
        self.fx_spin.setRange(0.0001, 100000.0)
        self.fx_spin.setDecimals(4)
        self.fx_spin.valueChanged.connect(self._commit_fx)
        form.addWidget(self.fx_spin, 2, 1)

        form.addWidget(QLabel("备注"), 2, 2)
        self.note_edit = QLineEdit()
        self.note_edit.editingFinished.connect(self._commit_note)
        form.addWidget(self.note_edit, 2, 3)
        lay.addLayout(form)

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setTextFormat(Qt.RichText)
        self.stats_label.setStyleSheet(
            "background:#eef4fb;border:1px solid #b8cfe0;padding:8px;border-radius:4px;")
        lay.addWidget(self.stats_label)

        lay.addWidget(QLabel("交易记录 (买入/申购/存入=投入, 其余=收回)"))
        self.tx_table = QTableWidget()
        self.tx_table.setColumnCount(7)
        self.tx_table.setHorizontalHeaderLabels(
            ["日期", "类型", "金额(条目币种)", "汇率", "人民币金额", "当日市值", "备注"])
        self.tx_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tx_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tx_table.cellDoubleClicked.connect(lambda *_: self.edit_transaction())
        lay.addWidget(self.tx_table)

        row = QHBoxLayout()
        b_add = QPushButton("添加交易")
        b_edit = QPushButton("编辑交易")
        b_del = QPushButton("删除交易")
        b_add.clicked.connect(self.add_transaction)
        b_edit.clicked.connect(self.edit_transaction)
        b_del.clicked.connect(self.delete_transaction)
        row.addWidget(b_add)
        row.addWidget(b_edit)
        row.addWidget(b_del)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    # ------------------------------------------------------------ 数据载入
    def _load_initial_data(self):
        candidate = self._default_data_path()
        if os.path.exists(candidate):
            try:
                self.portfolio = Portfolio.load_json(candidate)
                self.data_path = candidate
            except Exception as e:
                QMessageBox.warning(self, "载入失败", f"无法载入 {candidate}:\n{e}")

    def current_investment(self) -> Investment | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.portfolio.investments):
            return self.portfolio.investments[row]
        return None

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        """完整刷新：重建列表、表单、统计、交易表。用于结构性变化。"""
        self._loading = True
        try:
            cur = self.current_investment()
            self._reload_list(cur)
            self._load_detail(cur)
            self._load_stats(cur)
            self._load_transactions(cur)
            self._update_summary()
        finally:
            self._loading = False

    def _reload_list(self, cur: Investment | None):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for inv in self.portfolio.investments:
            item = QListWidgetItem(
                f"{inv.name}   ({inv.currency})  ¥{_fmt_num(inv.current_value_cny)}")
            item.setData(Qt.UserRole, inv.name)
            self.list_widget.addItem(item)
        if cur is not None:
            idx = self.portfolio.investments.index(cur)
            self.list_widget.setCurrentRow(idx)
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self.list_widget.blockSignals(False)

    def _recalc(self):
        """轻量刷新：只更新统计/汇总/交易表与列表文本，不回填表单输入框。
        用于金额/汇率等输入过程中，避免打断手动输入。"""
        inv = self.current_investment()
        self._update_list_text(inv)
        self._load_stats(inv)
        self._load_transactions(inv)
        self._update_summary()

    def _update_list_text(self, inv: Investment | None):
        if inv is None:
            return
        try:
            idx = self.portfolio.investments.index(inv)
        except ValueError:
            return
        item = self.list_widget.item(idx)
        if item is not None:
            item.setText(
                f"{inv.name}   ({inv.currency})  ¥{_fmt_num(inv.current_value_cny)}")

    def _load_detail(self, inv: Investment | None):
        if inv is None:
            self.name_edit.clear()
            self.itype_combo.setCurrentIndex(0)
            self.currency_combo.setCurrentIndex(0)
            self.value_spin.setValue(0)
            self.fx_spin.setValue(1.0)
            self.note_edit.clear()
            return
        self.name_edit.setText(inv.name)
        self.itype_combo.setCurrentText(inv.itype)
        self.currency_combo.setCurrentText(inv.currency)
        self.value_spin.setValue(inv.current_value)
        self.fx_spin.setValue(inv.current_fx)
        self.note_edit.setText(inv.note)
        self._sync_fx_enabled()

    def _load_stats(self, inv: Investment | None):
        if inv is None:
            self.stats_label.setText(
                "请在左侧新建投资条目，然后在右侧填写交易记录和当前市值。")
            return
        st = InvestmentStats(inv, date.today())
        c = inv.currency
        html = [
            f"<b>{inv.name}</b>  |  {inv.itype}  |  {c}",
            f"当前市值: {_fmt_num(inv.current_value)} {c}  ≈ ¥{_fmt_num(st.value_cny)}",
            f"累计投入(人民币): ¥{_fmt_num(st.paid)}",
            f"累计收益(人民币): ¥<b>{_fmt_num(st.profit)}</b>  "
            f"<span style='color:{_pct_color(st.simple_return)}'>"
            f"({_fmt_pct(st.simple_return)})</span>",
        ]
        days = st.hold_days()
        if days is not None:
            html.append(f"持有天数: {days}")
        approx = " <span style='color:#888'>*按成本估算</span>" if (
            st.twrr is not None and not any(t.holding_value is not None for t in st.txs)
        ) else ""
        html.append(f"<b>XIRR(年化):</b> <span style='color:{_pct_color(st.xirr)}'>"
                    f"{_fmt_pct(st.xirr)}</span>   |   "
                    f"<b>TWRR(年化):</b> <span style='color:{_pct_color(st.twrr)}'>"
                    f"{_fmt_pct(st.twrr)}</span>{approx}")
        if c != "CNY":
            fc = st.profit_fc
            approx_fc = " <span style='color:#888'>*按成本估算</span>" if (
                st.twrr_fc is not None and not any(t.holding_value is not None for t in st.txs)
            ) else ""
            html.append(f"外币收益: {_fmt_num(fc)} {c}  汇率变动: {_fmt_pct(st.fx_change)}")
            html.append(f"外币口径(不含汇率) XIRR: "
                        f"<span style='color:{_pct_color(st.xirr_fc)}'>{_fmt_pct(st.xirr_fc)}</span>"
                        f"   |   TWRR: "
                        f"<span style='color:{_pct_color(st.twrr_fc)}'>{_fmt_pct(st.twrr_fc)}</span>"
                        f"{approx_fc}")
        self.stats_label.setText("<br>".join(html))

    def _load_transactions(self, inv: Investment | None):
        self.tx_table.setRowCount(0)
        if inv is None:
            return
        txs = inv.sorted_transactions()
        self.tx_table.setRowCount(len(txs))
        for i, t in enumerate(txs):
            self.tx_table.setItem(i, 0, QTableWidgetItem(t.date.isoformat()))
            self.tx_table.setItem(i, 1, QTableWidgetItem(t.type))
            self.tx_table.setItem(i, 2, QTableWidgetItem(_fmt_num(t.amount, 4)))
            self.tx_table.setItem(i, 3, QTableWidgetItem(_fmt_num(t.fx, 4)))
            self.tx_table.setItem(i, 4, QTableWidgetItem(f"¥{_fmt_num(t.signed_cny, 2)}"))
            self.tx_table.setItem(i, 5, QTableWidgetItem(
                _fmt_num(t.holding_value, 2) if t.holding_value is not None else ""))
            self.tx_table.setItem(i, 6, QTableWidgetItem(t.note))
        header = self.tx_table.horizontalHeader()
        for col, w in enumerate([90, 70, 110, 70, 110, 110, 140]):
            header.resizeSection(col, w)
        header.setStretchLastSection(True)

    def _update_summary(self):
        ps = PortfolioStats(self.portfolio.investments, date.today())
        n = len(self.portfolio.investments)
        html = [
            f"<b>投资组合</b>  共 {n} 项",
            f"总市值: ¥{_fmt_num(ps.total_value_cny)}   "
            f"累计投入: ¥{_fmt_num(ps.paid)}   "
            f"累计收益: ¥<span style='color:{_pct_color(ps.profit)}'>{_fmt_num(ps.profit)}</span> "
            f"({_fmt_pct(ps.simple_return)})",
            f"组合 XIRR(年化): <span style='color:{_pct_color(ps.xirr)}'>{_fmt_pct(ps.xirr)}</span>",
        ]
        self.summary_label.setText(" | ".join(html))

    # ------------------------------------------------------------ 事件
    def _on_select(self):
        if self._loading:
            return
        self.refresh()

    def _selected_or_warn(self) -> Investment | None:
        inv = self.current_investment()
        if inv is None:
            QMessageBox.information(self, "提示", "请先在左侧选择一个投资条目。")
        return inv

    def _commit_name(self):
        if self._loading:
            return
        inv = self.current_investment()
        if inv is None:
            return
        new_name = self.name_edit.text().strip()
        if not new_name:
            self.name_edit.setText(inv.name)
            return
        if any(i.name == new_name and i is not inv for i in self.portfolio.investments):
            QMessageBox.warning(self, "重名", "投资名称不能重复。")
            self.name_edit.setText(inv.name)
            return
        inv.name = new_name
        self._save_and_refresh()

    def _commit_itype(self):
        if self._loading:
            return
        inv = self.current_investment()
        if inv:
            inv.itype = self.itype_combo.currentText()
            self._save_and_refresh()

    def _commit_currency(self):
        if self._loading:
            return
        inv = self.current_investment()
        if inv:
            new_cur = self.currency_combo.currentText()
            inv.currency = new_cur
            if new_cur == "CNY":
                inv.current_fx = 1.0
            else:
                inv.current_fx = DEFAULT_FX.get(new_cur, 1.0)
            self._sync_fx_enabled()
            self._save_and_refresh()

    def _sync_fx_enabled(self):
        non_cny = self.currency_combo.currentText() != "CNY"
        self.fx_spin.setEnabled(non_cny)

    def _commit_value(self):
        if self._loading:
            return
        inv = self.current_investment()
        if inv:
            inv.current_value = self.value_spin.value()
            self._save_and_recalc()

    def _commit_fx(self):
        if self._loading:
            return
        inv = self.current_investment()
        if inv:
            inv.current_fx = self.fx_spin.value()
            self._save_and_recalc()

    def _commit_note(self):
        if self._loading:
            return
        inv = self.current_investment()
        if inv:
            inv.note = self.note_edit.text().strip()
            self._save_and_refresh()

    def _save_and_refresh(self):
        self._auto_save()
        self.refresh()

    def _save_and_recalc(self):
        self._auto_save()
        self._recalc()

    def _default_data_path(self) -> str:
        return os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "portfolio.json"))

    def _auto_save(self):
        path = self.data_path or self._default_data_path()
        try:
            self.portfolio.save_json(path)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
        else:
            if self.data_path is None:
                self.data_path = path

    # ------------------------------------------------------------ 增删投资
    def add_investment(self):
        n = len(self.portfolio.investments) + 1
        name = f"投资{n}"
        while self.portfolio.find(name):
            n += 1
            name = f"投资{n}"
        self.portfolio.add(Investment(name=name))
        self.refresh()
        self.list_widget.setCurrentRow(len(self.portfolio.investments) - 1)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def delete_investment(self):
        inv = self._selected_or_warn()
        if inv is None:
            return
        ret = QMessageBox.question(
            self, "确认", f"删除投资条目“{inv.name}”及其全部交易记录？",
            QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self.portfolio.remove(inv)
        self._save_and_refresh()

    # ------------------------------------------------------------ 交易增删改
    def add_transaction(self):
        inv = self._selected_or_warn()
        if inv is None:
            return
        dlg = TransactionDialog(self, inv.currency)
        if dlg.exec() == QDialog.Accepted:
            inv.transactions.append(dlg.result_tx())
            self._save_and_refresh()

    def edit_transaction(self):
        inv = self._selected_or_warn()
        if inv is None:
            return
        row = self.tx_table.currentRow()
        txs = inv.sorted_transactions()
        if not (0 <= row < len(txs)):
            QMessageBox.information(self, "提示", "请先在表格中选择一行交易。")
            return
        old = txs[row]
        dlg = TransactionDialog(self, inv.currency, old)
        if dlg.exec() == QDialog.Accepted:
            new = dlg.result_tx()
            i = inv.transactions.index(old)
            inv.transactions[i] = new
            self._save_and_refresh()

    def delete_transaction(self):
        inv = self._selected_or_warn()
        if inv is None:
            return
        row = self.tx_table.currentRow()
        txs = inv.sorted_transactions()
        if not (0 <= row < len(txs)):
            QMessageBox.information(self, "提示", "请先在表格中选择一行交易。")
            return
        old = txs[row]
        inv.transactions.remove(old)
        self._save_and_refresh()

    # ------------------------------------------------------------ 文件操作
    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "打开数据", "", "数据文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            self.portfolio = Portfolio.load_json(path)
        except Exception as e:
            QMessageBox.critical(self, "打开失败", f"无法打开 {path}:\n{e}")
            return
        self.data_path = path
        self.refresh()

    def save_json_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "另存数据", "portfolio.json", "数据文件 (*.json)")
        if not path:
            return
        try:
            self.portfolio.save_json(path)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.data_path = path

    def export_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel", "投资数据.xlsx", "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            export_to_excel(path, self.portfolio)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            return
        QMessageBox.information(self, "导出成功", f"已导出到:\n{path}")

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Excel", "", "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            new_pf = import_from_excel(path)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return
        if (self.portfolio.investments or self.data_path):
            ret = QMessageBox.question(
                self, "确认", "导入将覆盖当前全部数据，是否继续？",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self.portfolio = new_pf
        self.data_path = None
        self.refresh()
        QMessageBox.information(
            self, "导入成功",
            f"已导入 {len(new_pf.investments)} 个投资条目。")

    def show_about(self):
        msg = (
            "<b>投资年化收益计算 (XIRR / TWRR)</b><br><br>"
            "支持：普通存款、股票、ETF、基金、理财。<br>"
            "任意类型均可选择币种；选择非人民币币种即按外币投资处理，"
            "每笔交易记录汇率，期末用当前汇率估值，人民币收益自动包含汇率波动。<br><br>"
            "<b>现金流约定</b>：买入/申购/存入 = 投入资金(负)；"
            "卖出/赎回/取出/分红/利息 = 收回资金(正)；当前市值作为期末正现金流。<br><br>"
            "<b>XIRR</b>：按交易日折算的人民币口径内部收益率(年化)。<br>"
            "<b>TWRR</b>：时间加权收益率。填“当日整仓市值”后计算精确值；"
            "未填时按成本估算(打星标注)。<br><br>"
            "<b>外币理财</b>：每笔交易记录汇率，期末用当前汇率估值，"
            "人民币收益已自动包含汇率波动；另显示“外币口径(不含汇率)”的 XIRR/TWRR，"
            "即纯按外币本金与收益计算的年化。<br><br>"
            "数据默认保存到程序目录下的 portfolio.json，"
            "可通过“文件→另存数据”更换位置；"
            "Excel 导出后也可再导入(可往返)。"
        )
        QMessageBox.information(self, "使用说明", msg)

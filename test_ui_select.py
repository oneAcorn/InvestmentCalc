"""UI 选择/删除/交易归属 回归验证（离屏）"""
import os
from datetime import date

from PySide6.QtWidgets import QApplication

from investapp.main_window import MainWindow
from investapp.models import Transaction

pf = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.json"))
if os.path.exists(pf):
    os.remove(pf)

app = QApplication([])
w = MainWindow()
w.show()

w.add_investment()
w.add_investment()
w.portfolio.investments[0].name = "A甲"
w.portfolio.investments[1].name = "B乙"
w.portfolio.investments[0].transactions.append(Transaction(date(2024, 1, 1), "买入", 100, 1.0))
w.portfolio.investments[1].transactions.append(Transaction(date(2024, 2, 1), "买入", 200, 1.0))
w.refresh()
app.processEvents()

# 1. 选中第二个条目 -> 交易表应显示乙的1行
w.list_widget.setCurrentRow(1)
app.processEvents()
print("sel1:", w.current_investment().name, "rows:", w.tx_table.rowCount())

# 2. 选中第二个条目后添加交易 -> 应加到乙
w.portfolio.investments[1].transactions.append(Transaction(date(2024, 3, 1), "分红", 50, 1.0))
w._save_and_refresh()
app.processEvents()
print("cnt A/B:", len(w.portfolio.investments[0].transactions),
      len(w.portfolio.investments[1].transactions))

# 3. 切换条目 -> 交易表跟随变化
w.list_widget.setCurrentRow(0)
app.processEvents()
print("sel2:", w.current_investment().name, "rows:", w.tx_table.rowCount())
w.list_widget.setCurrentRow(1)
app.processEvents()
print("sel3:", w.current_investment().name, "rows:", w.tx_table.rowCount())

# 4. 选中乙再删除 -> 应删乙
target = w.current_investment().name
w.portfolio.remove(w.current_investment())
w._save_and_refresh()
app.processEvents()
print("deleted:", target, "remaining:", [i.name for i in w.portfolio.investments])
print("sel_after:", w.current_investment().name if w.current_investment() else None)

if os.path.exists(pf):
    os.remove(pf)
w.close()
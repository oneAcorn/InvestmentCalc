"""计算与 Excel 往返验证（python test_calc.py）。"""
from datetime import date

from investapp.calc import InvestmentStats, PortfolioStats, twrr, xirr
from investapp.excel_io import export_to_excel, import_from_excel
from investapp.models import Investment, Portfolio, Transaction

PASS = 0


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        print(f"  [FAIL] {name}  {detail}")


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ---- XIRR ----
dates = [date(2023, 1, 1), date(2024, 1, 1)]
flows = [-10000.0, 11000.0]
r = xirr(dates, flows)
check("XIRR 一年 10%", approx(r, 0.1), r)

dates = [date(2023, 1, 1), date(2023, 7, 1), date(2024, 1, 1)]
flows = [-1000.0, -1000.0, 2100.0]
r = xirr(dates, flows)
check("XIRR 两笔投入", r is not None, r)
if r is not None:
    # 回代校验 NPV≈0
    t0 = dates[0]
    npv = sum(a * (1 + r) ** (-((d - t0).days) / 365.0) for d, a in zip(dates, flows))
    check("XIRR 回代 NPV≈0", abs(npv) < 1e-6, npv)

check("XIRR 空输入", xirr([], []) is None)
check("XIRR 全同号", xirr(dates, [-1, -1, -1]) is None)

# ---- TWRR ----
dates = [date(2023, 1, 1), date(2023, 7, 1)]
flows = [-10000.0, -5000.0]
vals = [0.0, 11000.0]  # 交易前市值
r = twrr(dates, flows, vals, date(2024, 1, 1), 17600.0)
check("TWRR 两期各10%=21%", approx(r, 0.21), r)

dates = [date(2023, 1, 1)]
flows = [-10000.0]
r = twrr(dates, flows, None, date(2024, 1, 1), 11000.0)
check("TWRR 无估值=按成本10%", approx(r, 0.1), r)

# ---- 组合模型统计 ----
inv1 = Investment(name="存款", itype="普通存款", currency="CNY",
                  current_value=11000.0, current_fx=1.0,
                  transactions=[
                      Transaction(date(2023, 1, 1), "存入", 10000.0, 1.0),
                  ])
inv2 = Investment(name="美元理财", itype="理财", currency="USD",
                  current_value=11000.0, current_fx=7.7,
                  transactions=[
                      Transaction(date(2023, 1, 1), "买入", 10000.0, 7.0),
                  ])
st2 = InvestmentStats(inv2, date(2024, 1, 1))
check("外币人民币收益", approx(st2.profit, 84700 - 70000, 1e-6), st2.profit)
check("外币收益USD", approx(st2.profit_fc, 1000.0, 1e-6), st2.profit_fc)
check("外币XIRR=21%", approx(st2.xirr, 0.21, 1e-6), st2.xirr)
check("外币口径XIRR(不含汇率)=10%", approx(st2.xirr_fc, 0.10, 1e-6), st2.xirr_fc)

# 旧数据兼容：外币理财 类型并入 理财
from investapp.models import Investment as _Inv
migrated = _Inv.from_dict({"name": "旧", "itype": "外币理财", "transactions": []}).itype
check("外币理财迁移为理财", migrated == "理财", migrated)

pf = Portfolio([inv1, inv2])
ps = PortfolioStats(pf.investments, date(2024, 1, 1))
check("组合总市值", approx(ps.total_value_cny, 11000 + 84700, 1e-6), ps.total_value_cny)
check("组合XIRR", ps.xirr is not None, ps.xirr)

# ---- Excel 往返 ----
import os
import tempfile

inv3 = Investment(name="股票", itype="股票", currency="CNY", current_value=5200.0,
                  current_fx=1.0,
                  transactions=[
                      Transaction(date(2024, 3, 1), "买入", 5000.0, 1.0,
                                  holding_value=5000.0, note="首笔"),
                      Transaction(date(2024, 6, 1), "分红", 200.0, 1.0),
                  ])
pf2 = Portfolio([inv1, inv2, inv3])
tmp = os.path.join(tempfile.gettempdir(), "test_portfolio.xlsx")
export_to_excel(tmp, pf2)
pf3 = import_from_excel(tmp)
ok = len(pf3.investments) == 3
ok = ok and pf3.find("存款").transactions[0].amount == 10000.0
ok = ok and pf3.find("股票").transactions[0].holding_value == 5000.0
ok = ok and pf3.find("股票").transactions[0].note == "首笔"
ok = ok and pf3.find("美元理财").transactions[0].fx == 7.0
check("Excel 导出/导入往返", ok)
os.remove(tmp)

print(f"\n通过 {PASS} 项检查")

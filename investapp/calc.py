"""收益计算：XIRR、TWRR、累计收益、汇率分解。"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from .models import Investment, Transaction


# ---------------------------------------------------------------- XIRR
def xirr(dates: List[date], amounts: List[float],
         max_iter: int = 300, tol: float = 1e-12) -> Optional[float]:
    """内部收益率(年化)。amounts 为现金流(投入为负、收回/期末市值为正)，单位为人民币。

    求解 sum(amount_i * (1+r)^(-(d_i - d_0)/365)) = 0。
    """
    if len(dates) != len(amounts) or len(dates) == 0:
        return None
    if all(a > 0 for a in amounts) or all(a < 0 for a in amounts):
        return None

    t0 = min(dates)
    days = [(d - t0).days for d in dates]

    def f(r: float) -> float:
        return sum(a * (1.0 + r) ** (-d / 365.0) for d, a in zip(days, amounts))

    lo, hi = -0.999999, 10.0
    flo, fhi = f(lo), f(hi)

    if flo * fhi > 0:
        for _ in range(120):
            if flo * fhi <= 0:
                break
            hi *= 2.0
            fhi = f(hi)
            if hi > 1e15:
                break
    if flo * fhi > 0:  # 极负收益：向 -1 方向继续寻找
        lo = -0.99999999
        flo = f(lo)

    if flo * fhi > 0:
        return None  # 无解

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) < tol:
            return mid
        if flo * fm <= 0.0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2.0


# ---------------------------------------------------------------- TWRR
def twrr(dates: List[date], amounts: List[float],
         valuations: Optional[List[Optional[float]]],
         end_date: date, end_value: float) -> Optional[float]:
    """时间加权收益率(年化)。

    amounts: 外部现金流(投入为负、收回为正，人民币)。
    valuations[i]: 第 i 笔现金流发生当日、该笔交易前的整仓市值(人民币)；
        可传 None(用成本估算)或整体传 None。
    end_date/end_value: 估值日与期末市值(人民币)。
    """
    if not dates or not amounts or len(dates) != len(amounts):
        return None
    if end_value is None or end_value < 0:
        return None
    pairs = sorted(zip(dates, amounts))
    prod = 1.0
    after = 0.0  # 上一笔现金流之后的市值(人民币)
    first_date = pairs[0][0]
    for i, (d, a) in enumerate(pairs):
        v_before = None
        if valuations is not None:
            v_before = valuations[i]
        if v_before is None:
            v_before = after  # 无估值时按成本(上笔后市值)估算
        if after > 0:
            prod *= v_before / after
        after = v_before - a  # 现金流为投资者视角：投入(负)使组合市值增加
    if after <= 0:
        return None
    prod *= end_value / after
    if prod <= 0:
        return None
    total_days = (end_date - first_date).days
    if total_days <= 0:
        return None
    return prod ** (365.0 / total_days) - 1.0


# ---------------------------------------------------------------- 单条投资
class InvestmentStats:
    def __init__(self, inv: Investment, valuation_date: date):
        self.inv = inv
        self.valuation_date = valuation_date
        txs = inv.sorted_transactions()
        self.txs = txs
        self.flows_cny = [t.signed_cny for t in txs]
        self.flows_fc = [t.signed for t in txs]
        self.dates = [t.date for t in txs]
        self.value_cny = inv.current_value_cny

        self.paid = -sum(a for a in self.flows_cny if a < 0)
        self.received = sum(a for a in self.flows_cny if a > 0)
        self.profit = self.value_cny + sum(self.flows_cny)
        self.simple_return = (self.profit / self.paid) if self.paid > 0 else None

        # 外币口径收益（仅对外币条目有意义）
        self.paid_fc = -sum(a for a in self.flows_fc if a < 0)
        self.profit_fc = None
        if inv.current_fx:
            self.profit_fc = self.value_cny / inv.current_fx + sum(self.flows_fc)

        # 汇率变动
        self.fx_change = None
        if inv.currency != "CNY" and txs:
            first_fx = txs[0].fx
            if first_fx:
                self.fx_change = inv.current_fx / first_fx - 1.0

        # XIRR（人民币口径，期末市值作为最后一笔正现金流）
        self.xirr = None
        if txs and self.value_cny >= 0:
            r = xirr(self.dates + [valuation_date], self.flows_cny + [self.value_cny])
            self.xirr = r

        # TWRR
        self.twrr = None
        if txs and self.value_cny >= 0:
            has_val = any(t.holding_value is not None for t in txs)
            vals = None
            if has_val:
                vals = [
                    (t.holding_value * t.fx) if t.holding_value is not None else None
                    for t in txs
                ]
            self.twrr = twrr(self.dates, self.flows_cny, vals,
                             valuation_date, self.value_cny)

        # 外币口径（不含汇率影响）：以外币自身的现金流与期末市值计算
        self.xirr_fc = None
        self.twrr_fc = None
        if inv.currency != "CNY" and txs and inv.current_value >= 0:
            r = xirr(self.dates + [valuation_date], self.flows_fc + [inv.current_value])
            self.xirr_fc = r
            has_val = any(t.holding_value is not None for t in txs)
            vals = None
            if has_val:
                vals = [t.holding_value if t.holding_value is not None else None
                        for t in txs]
            self.twrr_fc = twrr(self.dates, self.flows_fc, vals,
                                valuation_date, inv.current_value)

    def hold_days(self) -> Optional[int]:
        if not self.dates:
            return None
        return (self.valuation_date - self.dates[0]).days


# ---------------------------------------------------------------- 组合汇总
class PortfolioStats:
    def __init__(self, investments: List[Investment], valuation_date: date):
        self.valuation_date = valuation_date
        self.dates: List[date] = []
        self.flows: List[float] = []
        self.total_value_cny = 0.0
        self.paid = 0.0
        self.received = 0.0

        for inv in investments:
            txs = inv.sorted_transactions()
            for t in txs:
                self.dates.append(t.date)
                self.flows.append(t.signed_cny)
            self.total_value_cny += inv.current_value_cny
            self.paid += -sum(a for a in (t.signed_cny for t in txs) if a < 0)
            self.received += sum(a for a in (t.signed_cny for t in txs) if a > 0)

        self.profit = self.total_value_cny + sum(self.flows)
        self.simple_return = (self.profit / self.paid) if self.paid > 0 else None
        self.xirr = None
        if self.dates:
            r = xirr(self.dates + [valuation_date], self.flows + [self.total_value_cny])
            self.xirr = r
        self.twrr = None  # 组合级 TWRR 需逐日估值，未提供时不做组合级估算

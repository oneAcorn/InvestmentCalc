"""数据模型：投资条目、交易记录、投资组合。

现金流符号约定（与 Excel XIRR 一致）：
    投入（买入/申购/存入）-> 负现金流
    收回（卖出/赎回/取出/分红/利息）-> 正现金流
    期末市值 -> 正现金流
外币条目：金额以条目币种记录，另有 汇率 = 1 单位条目币种兑换多少人民币。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

BASE_CURRENCY = "CNY"

INVESTMENT_TYPES = ["普通存款", "股票", "ETF", "基金", "理财"]
CURRENCIES = ["CNY", "USD", "HKD", "EUR", "JPY", "GBP"]

TRANSACTION_TYPES = ["买入", "卖出", "存入", "取出", "申购", "赎回", "分红", "利息"]

MONEY_IN = {"买入", "申购", "存入"}
MONEY_OUT = {"卖出", "赎回", "取出", "分红", "利息"}

DEFAULT_FX = {"CNY": 1.0, "USD": 7.20, "HKD": 0.92, "EUR": 7.80, "JPY": 0.048, "GBP": 9.10}


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise ValueError(f"无法解析日期: {value!r}")


def normalize_itype(value: str) -> str:
    """兼容旧数据：外币理财类型已并入“理财”（币种由 currency 字段表达）。"""
    if value == "外币理财":
        return "理财"
    return value


@dataclass
class Transaction:
    date: date
    type: str = "买入"
    amount: float = 0.0      # 以条目币种计的正数金额
    fx: float = 1.0          # 条目币种 -> 人民币 汇率（人民币条目为 1.0）
    holding_value: Optional[float] = None  # 当日整仓市值（条目币种），用于精确 TWRR，可留空
    note: str = ""

    @property
    def signed(self) -> float:
        """投资者视角现金流：投入为负、收回为正。"""
        return -self.amount if self.type in MONEY_IN else self.amount

    @property
    def signed_cny(self) -> float:
        return self.signed * self.fx


@dataclass
class Investment:
    name: str
    itype: str = "理财"
    currency: str = "CNY"
    current_value: float = 0.0   # 条目币种
    current_fx: float = 1.0      # 估值时的汇率
    note: str = ""
    transactions: List[Transaction] = field(default_factory=list)

    @property
    def current_value_cny(self) -> float:
        return self.current_value * self.current_fx

    def sorted_transactions(self) -> List[Transaction]:
        return sorted(self.transactions, key=lambda t: t.date)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "itype": self.itype,
            "currency": self.currency,
            "current_value": self.current_value,
            "current_fx": self.current_fx,
            "note": self.note,
            "transactions": [
                {
                    "date": t.date.isoformat(),
                    "type": t.type,
                    "amount": t.amount,
                    "fx": t.fx,
                    "holding_value": t.holding_value,
                    "note": t.note,
                }
                for t in self.transactions
            ],
        }

    @staticmethod
    def from_dict(d: dict) -> "Investment":
        txs = []
        for td in d.get("transactions", []):
            txs.append(
                Transaction(
                    date=parse_date(td["date"]),
                    type=td.get("type", "买入"),
                    amount=float(td.get("amount", 0.0)),
                    fx=float(td.get("fx", 1.0)),
                    holding_value=(None if td.get("holding_value") is None
                                   else float(td["holding_value"])),
                    note=td.get("note", ""),
                )
            )
        return Investment(
            name=d["name"],
            itype=normalize_itype(d.get("itype", "理财")),
            currency=d.get("currency", "CNY"),
            current_value=float(d.get("current_value", 0.0)),
            current_fx=float(d.get("current_fx", 1.0)),
            note=d.get("note", ""),
            transactions=txs,
        )


class Portfolio:
    def __init__(self, investments: Optional[List[Investment]] = None):
        self.investments: List[Investment] = investments or []

    def find(self, name: str) -> Optional[Investment]:
        for inv in self.investments:
            if inv.name == name:
                return inv
        return None

    def add(self, inv: Investment) -> None:
        self.investments.append(inv)

    def remove(self, inv: Investment) -> None:
        if inv in self.investments:
            self.investments.remove(inv)

    def to_dict(self) -> dict:
        return {"base_currency": BASE_CURRENCY,
                "investments": [i.to_dict() for i in self.investments]}

    @staticmethod
    def from_dict(d: dict) -> "Portfolio":
        return Portfolio([Investment.from_dict(x) for x in d.get("investments", [])])

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_json(path: str) -> "Portfolio":
        with open(path, "r", encoding="utf-8") as f:
            return Portfolio.from_dict(json.load(f))

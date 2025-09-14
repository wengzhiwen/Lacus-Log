"""校验日报CSV内部一致性的脚本

校验项：
- 机师分成/公司分成金额 == 流水 × ((当前分成比例/50)*42% / (42%-…))
- 产生返点 == 流水 × 返点比例
- 当日毛利 == 公司分成 + 产生返点 - 底薪
- 月累计毛利 == 月累计公司分成 + 月累计返点 - 月累计底薪

用法：
  PYTHONPATH=. venv/bin/python scripts/validate_daily_csv.py log/daily_report_*.csv
若不传参数，默认扫描 log/ 目录下所有 daily_report_*.csv
"""

from __future__ import annotations

import csv
import glob
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict


def parse_money(s: str) -> Decimal:
    s = s.strip().replace(",", "")
    return Decimal(s) if s else Decimal("0")


def parse_percent(s: str) -> Decimal:
    s = s.strip().replace("%", "")
    if s == "":
        return Decimal("0")
    return (Decimal(s) / Decimal("100")).quantize(Decimal("0.0001"))


def q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def almost_equal(a: Decimal, b: Decimal, tol: Decimal = Decimal("0.02")) -> bool:
    return abs(a - b) <= tol


def validate_file(path: str) -> Dict[str, int]:
    errs = 0
    rows = 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1

            revenue = parse_money(row["流水"])
            commission_rate_base = row["当前分成比例"].strip()
            pilot_share = parse_money(row["机师分成"])
            company_share = parse_money(row["公司分成"])
            rebate_rate = parse_percent(row["返点比例"])  # 0~1
            rebate_amount = parse_money(row["产生返点"])
            base_salary = parse_money(row["底薪"])
            daily_profit = parse_money(row["当日毛利"])

            month_company_share = parse_money(row["月累计公司分成"])
            month_rebate = parse_money(row["月累计返点"])
            month_base_salary = parse_money(row["月累计底薪"])
            month_profit = parse_money(row["月累计毛利"])

            # 分成折算
            assert commission_rate_base.endswith("%"), "当前分成比例应为百分比"
            base_rate = Decimal(commission_rate_base[:-1])  # 0~50
            pilot_rate_pct = (base_rate / Decimal("50")) * Decimal("42")  # %
            company_rate_pct = Decimal("42") - pilot_rate_pct

            calc_pilot = q2(revenue * pilot_rate_pct / Decimal("100"))
            calc_company = q2(revenue * company_rate_pct / Decimal("100"))

            if not almost_equal(calc_pilot, pilot_share) or not almost_equal(calc_company, company_share):
                errs += 1

            # 返点与毛利
            calc_rebate = q2(revenue * rebate_rate)
            if not almost_equal(calc_rebate, rebate_amount):
                errs += 1

            calc_daily_profit = q2(company_share + rebate_amount - base_salary)
            if not almost_equal(calc_daily_profit, daily_profit):
                errs += 1

            # 月累计毛利
            calc_month_profit = q2(month_company_share + month_rebate - month_base_salary)
            if not almost_equal(calc_month_profit, month_profit):
                errs += 1

    return {"rows": rows, "errors": errs}


def main():
    files = sys.argv[1:]
    if not files:
        files = sorted(glob.glob(os.path.join("log", "daily_report_*.csv")))
    total_rows = 0
    total_errs = 0
    for fp in files:
        res = validate_file(fp)
        total_rows += res["rows"]
        total_errs += res["errors"]
        print(f"校验: {fp} -> 行数={res['rows']} 错误数={res['errors']}")
    print(f"合计: 行数={total_rows} 错误数={total_errs}")


if __name__ == "__main__":
    main()

"""Synthetic contract/rule consistency; private snapshots are never test inputs."""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_keyed_rules_and_synthetic_contract_have_unique_matches():
    rules = yaml.safe_load((ROOT / "cash-rules.yaml").read_text())["rules"]
    fixture = yaml.safe_load((ROOT / "tests/fixtures/degiro_contract.yaml").read_text())
    for expected, row in fixture["cash_movements"].items():
        matches = [name for name, rule in rules.items()
                   if row["type"] == rule["type"] and (
                       row["description"] == rule["description_exact"]
                       if "description_exact" in rule else
                       re.fullmatch(rule["description_pattern"], row["description"]))]
        assert matches == [expected]
    assert rules["flatex_interest"]["treatment"] == "zero_interest"
    assert rules["monetary_fund_compensation"]["treatment"] == "positive_compensation"
    assert rules["monetary_fund_compensation"]["sign"] == "positive"

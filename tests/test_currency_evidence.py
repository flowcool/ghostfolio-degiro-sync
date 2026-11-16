"""Currency proof through destination reads and exact quote conversions."""
from copy import deepcopy
from decimal import Decimal

import pytest

from ghostfolio_degiro_sync import ghostfolio
from ghostfolio_degiro_sync import currencies


@pytest.mark.parametrize('currency', ['CAD', 'CHF', 'GBP', 'JPY', 'EUR', 'USD'])
def test_existing_activity_uses_its_own_profile_currency_without_mutation(currency):
    row = {'currency': None, 'assetProfile': {
        'symbol': 'SYNTHETIC', 'dataSource': 'YAHOO', 'currency': currency}}
    before = deepcopy(row)
    assert ghostfolio.effective_activity_currency(row)['currency'] == currency
    assert row == before


@pytest.mark.parametrize('code,expected', [('JPY', '1'), ('CAD', '.01'), ('KWD', '.001'), ('CLF', '.0001'), ('GBp', '1')])
def test_monetary_precision_comes_from_currency_reference(code, expected):
    assert currencies.quantum(code) == Decimal(expected)


@pytest.mark.parametrize('row', [
    {'assetProfile': {'symbol': 'TEST', 'dataSource': 'YAHOO', 'currency': 'CAD'}},
    {'currency': None, 'assetProfile': None, 'SymbolProfile': {'symbol': 'TEST', 'dataSource': 'YAHOO', 'currency': 'CAD'}},
    {'currency': None, 'assetProfile': {'symbol': '', 'dataSource': 'YAHOO', 'currency': 'CAD'}},
    {'currency': None, 'assetProfile': {'symbol': 'TEST', 'dataSource': 'OTHER', 'currency': 'CAD'}},
    {'currency': 'made-up'}, {'currency': ''}, {'currency': 123},
])
def test_missing_or_invalid_currency_never_inherits_unrelated_evidence(row):
    assert currencies.effective_currency(row)['effective'] is None
    with pytest.raises(RuntimeError, match='Unverified Ghostfolio activity currency'):
        ghostfolio.effective_activity_currency(row)


def test_readable_code_with_no_monetary_unit_does_not_default_to_cents():
    assert currencies.effective_currency({'currency': 'XAU'})['effective'] == 'XAU'
    assert currencies.quantum('XAU') is None
    with pytest.raises(RuntimeError):
        currencies.quote_factor('XAU', 'XAU')


@pytest.mark.parametrize('source,quote,expected', [('GBP', 'GBp', '100'), ('GBp', 'GBP', '.01'), ('GBp', 'GBp', '1'), ('ILS', 'ILA', '100'), ('ZAR', 'ZAc', '100')])
def test_quote_conversion_is_an_exact_unit_relation(source, quote, expected):
    assert currencies.quote_factor(source, quote) == Decimal(expected)


@pytest.mark.parametrize('source,quote', [('GBP', 'USD'), ('CAD', 'EUR'), ('GBP', 'GBX'), ('USD', 'USX')])
def test_unproved_currency_conversion_has_no_ticker_or_rate_fallback(source, quote):
    with pytest.raises(RuntimeError):
        currencies.quote_factor(source, quote)

"""Offline regression subset from the pinned IBKR Ghostfolio helpers.

Only tests of the immutable broker-agnostic core are retained. Module import is
redirected; the response fixture is functional instead of a class. IBKR comments
in fixtures are opaque identities and deliberately exercise the unmodified core.
"""
import pytest
from types import SimpleNamespace

import ghostfolio_core as m

CFG = {"ghost_host": "http://ghost:3333", "ghost_token": "tok", "dry_run": False}


def Resp(body=None, status=200, text=""):
    def response_json():
        if body is None:
            raise ValueError("no json")
        return body

    def raise_for_status():
        if status >= 400:
            raise m.requests.HTTPError(str(status))

    return SimpleNamespace(json=response_json, raise_for_status=raise_for_status,
                           status_code=status, text=text)



def activity(profile_key="assetProfile", **kw):
    """Build a valid current or legacy activity fixture with field overrides."""
    a = {"type": "BUY", "quantity": 10, "comment": None, "accountId": "acc", "date": "2026-08-01T00:00:00.000Z",
         profile_key: {"symbol": "KO", "isin": "US1912161007", "dataSource": "YAHOO"}}
    a.update(kw)
    return a



def serve(monkeypatch, body, status=200):
    """Stub Ghostfolio GET requests with an isolated response body."""
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Resp(body, status))



def _unresolved_400(symbol, index=0):
    """A Ghostfolio import 400 body for a symbol the data source cannot resolve."""
    return {"error": "Bad Request", "statusCode": 400,
            "message": [f'activities.{index}.symbol ("{symbol}") '
                        f'cannot be resolved by the data source ("YAHOO")']}



def sequence_post(monkeypatch, responses):
    """Serve the given responses to successive POSTs; record the sent batches."""
    sent = []
    it = iter(responses)

    def _post(url, headers, json, timeout):
        sent.append(json["activities"])
        return next(it)
    monkeypatch.setattr(m.requests, "post", _post)
    return sent



def test_import_with_nothing_to_do_sends_nothing(monkeypatch):
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: pytest.fail("POST must not be sent"))
    assert m.ghost_import_activities(CFG, []) == ([], True)



def test_dry_run_never_posts(monkeypatch):
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: pytest.fail("POST must not be sent"))
    acts = [{"type": "BUY"}]
    assert m.ghost_import_activities({**CFG, "dry_run": True}, acts) == (acts, True)



def test_import_success_returns_all_activities(monkeypatch):
    acts = [import_candidate("IBKR#1"), import_candidate("IBKR#2")]
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": [created(a) for a in acts]}, 201))
    assert m.ghost_import_activities(CFG, acts) == (acts, True)



def test_unknown_400_fails_hard_without_retry(monkeypatch):
    """A non per-symbol 400 (e.g. too many activities) fails hard, no retry."""
    sent = sequence_post(monkeypatch, [Resp({"message": ["Too many activities (1 at most)"]}, 400)])
    assert m.ghost_import_activities(CFG, [{"symbol": "KO"}]) == ([], False)
    assert len(sent) == 1                                                   # no retry



def test_import_network_error_returns_false(monkeypatch):
    def boom(*a, **k):
        raise m.requests.ConnectionError("down")
    monkeypatch.setattr(m.requests, "post", boom)
    assert m.ghost_import_activities(CFG, [{"symbol": "KO"}]) == ([], False)



def test_import_short_accepted_count_is_not_a_failure(monkeypatch):
    acts = [import_candidate("IBKR#1"), import_candidate("IBKR#2")]
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": [created(acts[1])]}, 201))
    assert m.ghost_import_activities(CFG, acts) == ([acts[1]], True)



def test_parse_unresolved_symbol():
    assert m.parse_unresolved_symbol(_unresolved_400("XYZ")) == "XYZ"
    # Raw escaped JSON text (no decoded body) still parses.
    assert m.parse_unresolved_symbol(None, 'symbol (\\"XYZ\\") cannot be resolved '
                                           'by the data source (\\"YAHOO\\")') == "XYZ"
    # Not a per-symbol resolution error -> None (must not be retried).
    assert m.parse_unresolved_symbol({"message": ["Too many activities (1 at most)"]}) is None
    assert m.parse_unresolved_symbol(None, "") is None



def test_unresolved_symbol_is_dropped_and_batch_retried(monkeypatch):
    acts = [import_candidate("IBKR#1"), {**import_candidate("IBKR#2"), "symbol": "BADSYM"},
            {**import_candidate("IBKR#3"), "symbol": "AAPL"}]
    sent = sequence_post(monkeypatch, [
        Resp(_unresolved_400("BADSYM", index=1), 400),
        Resp({"activities": [created(acts[0]), created(acts[2])]}, 201),
    ])
    imported, ok = m.ghost_import_activities(CFG, acts)
    assert [a["symbol"] for a in imported] == ["KO", "AAPL"]                 # BADSYM dropped
    assert ok is False                                                      # degraded -> exit 1
    assert len(sent) == 2                                                   # one retry
    assert [a["symbol"] for a in sent[1]] == ["KO", "AAPL"]                 # retry excludes BADSYM



def test_all_symbols_unresolved_imports_nothing(monkeypatch):
    acts = [{"symbol": "BAD1"}, {"symbol": "BAD2"}]
    sequence_post(monkeypatch, [
        Resp(_unresolved_400("BAD1"), 400),
        Resp(_unresolved_400("BAD2"), 400),
    ])
    assert m.ghost_import_activities(CFG, acts) == ([], False)



def test_unmatched_rejected_symbol_aborts_without_looping(monkeypatch):
    """A rejected symbol absent from the batch must not spin the retry loop."""
    acts = [{"symbol": "KO"}]
    sent = sequence_post(monkeypatch, [Resp(_unresolved_400("NOTSENT"), 400)] * 5)
    assert m.ghost_import_activities(CFG, acts) == ([], False)
    assert len(sent) == 1                                                   # aborted, no loop



def test_find_account_by_name_and_missing_account(monkeypatch):
    serve(monkeypatch, {"accounts": [{"id": "1", "name": "IBKR"}, {"id": "2", "name": "PEA"}]})
    assert m.ghost_find_account_id(CFG, "PEA") == "2"
    assert m.ghost_find_account_id(CFG, "nope") is None



def test_cash_balance_payload_is_the_five_whitelisted_fields(monkeypatch):
    sent = {}
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: Resp(
        {"id": "9", "currency": "EUR", "name": "IBKR", "platformId": "p1", "comment": "x",
         "isExcluded": False, "balance": 1, "value": 5}))
    monkeypatch.setattr(m.requests, "put", lambda url, headers, json, timeout: sent.update(json) or Resp({}, 200))
    assert m.ghost_update_cash_balance(CFG, "9", 123.456) is True
    assert sent == {"balance": 123.456, "currency": "EUR", "id": "9", "name": "IBKR", "platformId": "p1"}



def test_cash_balance_dry_run_does_not_touch_the_api(monkeypatch):
    monkeypatch.setattr(m.requests, "get", lambda *a, **k: pytest.fail("no API call in dry run"))
    assert m.ghost_update_cash_balance({**CFG, "dry_run": True}, "9", 1.0) is True



def import_candidate(comment="IBKR#one"):
    return {"accountId": "synthetic", "comment": comment, "symbol": "KO", "type": "BUY",
            "quantity": 10, "unitPrice": 60, "fee": 1, "currency": "USD", "dataSource": "YAHOO",
            "date": "2026-08-01T00:00:00Z"}



def created(candidate):
    return {**candidate, "id": "created-" + candidate["comment"],
            "assetProfile": {"symbol": candidate["symbol"], "dataSource": candidate["dataSource"]}}



@pytest.mark.parametrize("body", [None, {}, {"activities": [{}]},
                                     {"activities": [import_candidate("unknown")]},
                                     {"activities": [import_candidate(), import_candidate()]},
                                     {"activities": [{**import_candidate(), "quantity": 99}]},
                                     {"activities": [{**import_candidate(), "error": "duplicate"}]}])
def test_unknown_acceptance_is_not_assumed_and_blocks_target(monkeypatch, body):
    cfg = {**CFG}
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp(body, 201))
    assert m.ghost_import_activities(cfg, [import_candidate()]) == ([], False)
    assert cfg["_uncertain_import_accounts"] == {"synthetic"}



def test_server_empty_created_list_changes_no_bookkeeping(monkeypatch):
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": []}, 201))
    assert m.ghost_import_activities({**CFG}, [import_candidate()]) == ([], True)



def test_created_rows_map_to_original_candidates_despite_enriched_profile(monkeypatch):
    candidate = import_candidate()
    server_row = {**created(candidate), "date": "2026-08-01T00:00:00.000Z",
                  "assetProfile": {"symbol": "CANONICAL", "dataSource": "YAHOO"}}
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": [server_row]}, 201))
    assert m.ghost_import_activities({**CFG}, [candidate]) == ([{**candidate, "symbol": "CANONICAL"}], True)



@pytest.mark.parametrize("field,value", [("id", None), ("id", ""), ("date", None), ("date", "bad"),
                                        ("date", "2026-08-02T00:00:00Z"),
                                        ("date", "2026-08-01T00:00:00"),
                                        ("assetProfile", None),
                                        ("assetProfile", {"symbol": "KO", "dataSource": "MANUAL"}),
                                        ("assetProfile", {"symbol": "", "dataSource": "YAHOO"})])
def test_created_identity_date_and_source_required(monkeypatch, field, value):
    candidate = import_candidate()
    row = created(candidate)
    row[field] = value
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": [row]}, 201))
    cfg = {**CFG}
    assert m.ghost_import_activities(cfg, [candidate]) == ([], False)
    assert cfg["_uncertain_import_accounts"] == {"synthetic"}



@pytest.mark.parametrize("field", ["quantity", "unitPrice", "fee"])
@pytest.mark.parametrize("value", [True, False, None, float("nan"), float("inf"), "1"])
def test_response_financial_evidence_is_numeric_finite_and_not_boolean(field, value):
    candidate = {**import_candidate(), field: 1}
    row = {**created(candidate), field: value}
    with pytest.raises(RuntimeError, match="financial evidence"):
        m.accepted_import_subset([candidate], {"activities": [row]})



def test_repeated_created_id_does_not_prove_two_created_buys():
    first, second = import_candidate("IBKR#1"), import_candidate("IBKR#2")
    rows = [created(first), {**created(second), "id": created(first)["id"]}]
    with pytest.raises(RuntimeError, match="created identity"):
        m.accepted_import_subset([first, second], {"activities": rows})



def test_excluded_empty_target_account_is_not_syncable(monkeypatch):
    serve(monkeypatch, {"accounts": [{"id": "excluded", "name": "IBKR",
                                     "tags": [{"id": "f2e868af-8333-459f-b161-cbc6544c24bd"}]}]})
    with pytest.raises(RuntimeError, match="excluded"):
        m.ghost_find_account_id(CFG, "IBKR")



def test_created_inactive_row_does_not_contribute_active_holding():
    candidate = import_candidate()
    row = {**created(candidate), "tags": [{"id": "0c077abd-eca2-4cbb-818c-6cefbf2d169a"}]}
    with pytest.raises(RuntimeError, match="inactive"):
        m.accepted_import_subset([candidate], {"activities": [row]})



def test_exact_import_shape_without_tags_does_not_hide_future_draft():
    candidate = {**import_candidate(), "date": "2099-08-01T00:00:00Z"}
    with pytest.raises(RuntimeError, match="inactive"):
        m.accepted_import_subset([candidate], {"activities": [created(candidate)]})



@pytest.mark.parametrize("profile_key", ["assetProfile", "SymbolProfile"])
def test_created_response_accepts_current_and_legacy_profiles(monkeypatch, profile_key):
    candidate = import_candidate()
    row = created(candidate)
    if profile_key == "SymbolProfile":
        row[profile_key] = row.pop("assetProfile")
    else:
        row["SymbolProfile"] = {"symbol": "STALE", "dataSource": "MANUAL"}
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": [row]}, 201))
    cfg = {**CFG, "_uncertain_import_accounts": set()}
    assert m.ghost_import_activities(cfg, [candidate]) == ([candidate], True)
    assert not cfg.get("_uncertain_import_accounts")



@pytest.mark.parametrize("profile", [None, {}, [], {"symbol": "", "dataSource": "YAHOO"},
                                     {"symbol": "KO", "dataSource": "MANUAL"}])
def test_created_response_invalid_current_profile_cannot_use_legacy(monkeypatch, profile):
    candidate = import_candidate()
    row = {**created(candidate), "assetProfile": profile,
           "SymbolProfile": {"symbol": "KO", "dataSource": "YAHOO"}}
    monkeypatch.setattr(m.requests, "post", lambda *a, **k: Resp({"activities": [row]}, 201))
    cfg = {**CFG, "_uncertain_import_accounts": set()}
    assert m.ghost_import_activities(cfg, [candidate]) == ([], False)
    assert cfg["_uncertain_import_accounts"] == {"synthetic"}

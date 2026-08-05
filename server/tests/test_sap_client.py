import pytest

import config
import sap_client


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def _configure(monkeypatch, url="https://fake.example/sap", user="u", pw="p", retries=2):
    monkeypatch.setattr(config, "SAP_ICF_URL", url)
    monkeypatch.setattr(config, "SAP_ICF_USERNAME", user)
    monkeypatch.setattr(config, "SAP_ICF_PASSWORD", pw)
    monkeypatch.setattr(config, "SAP_ICF_MAX_RETRIES", retries)
    monkeypatch.setattr(config, "SAP_ICF_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(sap_client.time, "sleep", lambda s: None)


def _call(**overrides):
    kwargs = dict(
        matnr="SCRAP-WP", board_length_cm=240, board_width_cm=120,
        product_area_cm2=18000, scrap_area_cm2=10800, source_id="S1",
    )
    kwargs.update(overrides)
    return sap_client.post_remnant(**kwargs)


def test_missing_config_raises(monkeypatch):
    monkeypatch.setattr(config, "SAP_ICF_URL", None)
    monkeypatch.setattr(config, "SAP_ICF_USERNAME", None)
    monkeypatch.setattr(config, "SAP_ICF_PASSWORD", None)
    with pytest.raises(sap_client.SapConfigError):
        _call()


def test_non_numeric_board_length_rejected_before_any_http_call(monkeypatch):
    _configure(monkeypatch)
    calls = []
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: calls.append(1))
    result = _call(board_length_cm="abc")
    assert result["ok"] is False
    assert "數值" in result["error"]
    assert calls == []


def test_zero_or_negative_required_field_rejected_before_any_http_call(monkeypatch):
    _configure(monkeypatch)
    calls = []
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: calls.append(1))
    result = _call(product_area_cm2=0)
    assert result["ok"] is False
    assert "大於 0" in result["error"]
    assert calls == []


def test_product_area_exceeding_board_area_rejected_before_any_http_call(monkeypatch):
    _configure(monkeypatch)
    calls = []
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: calls.append(1))
    result = _call(board_length_cm=240, board_width_cm=120, product_area_cm2=99999)
    assert result["ok"] is False
    assert "原紙板面積" in result["error"]
    assert calls == []


def test_success_returns_batch_bin_zone_and_string_coerced_payload(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(200, {
            # SAP's real field for the area it confirms back is "area", not
            # "remnant_area" -- this fake response deliberately mirrors that
            # real shape so this test actually exercises the data.get("area")
            # mapping in sap_client.py, not a fictional key.
            "status": "S", "guid": "G1", "board_area": "28800.000",
            "product_area": "18000.000", "area": "10800.000",
            "batch": "0000000243", "bin_zone": "B-1",
            "message": "OK MatDoc:4900011979",
        }),
    )
    # product_area_cm2 (one unit's own area) and scrap_area_cm2 (the leftover's
    # precisely-computed area, e.g. after 9 copies of the product were packed in)
    # are deliberately different numbers here -- this is the product_fit_count > 1
    # case where sending the wrong one would matter.
    result = _call(board_length_cm=240, board_width_cm=120, product_area_cm2=18000, scrap_area_cm2=10800)
    assert result["ok"] is True
    assert result["guid"] == "G1"
    assert result["batch"] == "0000000243"
    assert result["bin_zone"] == "B-1"
    assert result["remnant_area"] == "10800.000"
    assert "MatDoc" in result["message"]
    assert result["payload"]["board_length"] == "240"
    assert result["payload"]["board_width"] == "120"
    assert result["payload"]["product_area"] == "18000"
    assert result["payload"]["zone"] == "SCRAP-WP"  # defaults to matnr
    assert result["payload"]["plant"] == "2604"
    assert result["payload"]["sloc"] == "100B"
    assert result["payload"]["quantity"] == "1"
    assert result["payload"]["unit"] == "CM"
    assert "scrap_length" not in result["payload"]
    assert "scrap_width" not in result["payload"]
    assert "charg" not in result["payload"]
    assert "length" not in result["payload"]
    assert "width" not in result["payload"]
    assert "height" not in result["payload"]
    # The core assertion this test exists for: precomputed_area must be the
    # leftover's own area (scrap_area_cm2), never product_area_cm2.
    assert result["payload"]["precomputed_area"] == "10800"
    assert result["payload"]["precomputed_area"] != result["payload"]["product_area"]


def test_optional_fields_are_included_when_supplied(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(200, {"status": "S"}),
    )
    result = _call(
        zone="ZONE-X", plant="9999", sloc="200A", quantity=3,
        scrap_length_cm=50, scrap_width_cm=30,
    )
    assert result["payload"]["zone"] == "ZONE-X"
    assert result["payload"]["plant"] == "9999"
    assert result["payload"]["sloc"] == "200A"
    assert result["payload"]["quantity"] == "3"
    assert result["payload"]["length"] == "50"
    assert result["payload"]["width"] == "30"


def test_sap_level_failure_status_e(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(200, {"status": "E", "guid": None}),
    )
    result = _call()
    assert result["ok"] is False
    assert result["sap_status"] == "E"


@pytest.mark.parametrize("code", [401, 403, 405])
def test_fixed_message_error_codes(monkeypatch, code):
    _configure(monkeypatch)
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: _FakeResponse(code))
    result = _call()
    assert result["ok"] is False
    assert result["http_status"] == code
    assert result["error"] == sap_client.FRIENDLY_ERRORS[code]


@pytest.mark.parametrize("code", [400, 404, 422])
def test_body_message_error_codes_prefer_sap_message(monkeypatch, code):
    _configure(monkeypatch)
    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(code, {"status": "E", "message": "成品面積超過原紙板"}),
    )
    result = _call()
    assert result["ok"] is False
    assert result["http_status"] == code
    assert result["error"] == "成品面積超過原紙板"


@pytest.mark.parametrize("code", [400, 404, 422])
def test_body_message_error_codes_fall_back_when_body_not_json(monkeypatch, code):
    _configure(monkeypatch)
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: _FakeResponse(code))
    result = _call()
    assert result["ok"] is False
    assert result["error"] == sap_client.BODY_MESSAGE_ERRORS[code]


def test_401_is_never_retried(monkeypatch):
    _configure(monkeypatch, retries=3)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _FakeResponse(401)

    monkeypatch.setattr(sap_client.requests, "post", fake_post)
    _call()
    assert len(calls) == 1


def test_connection_error_is_retried_up_to_cap(monkeypatch):
    _configure(monkeypatch, retries=2)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        raise sap_client.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(sap_client.requests, "post", fake_post)
    result = _call()
    assert result["ok"] is False
    assert len(calls) == 1 + 2  # initial attempt + 2 retries


def test_non_json_response_is_handled(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: _FakeResponse(200, json_data=None))
    result = _call()
    assert result["ok"] is False
    assert "JSON" in result["error"]


def test_unexpected_status_code_is_handled(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(sap_client.requests, "post", lambda *a, **k: _FakeResponse(500, text="internal error"))
    result = _call()
    assert result["ok"] is False
    assert result["http_status"] == 500


# --- post_remnant_simple: a deliberately separate, parallel path -- these
# tests never touch post_remnant()/_call() above, and vice versa. ---

def test_post_remnant_simple_missing_config_raises(monkeypatch):
    monkeypatch.setattr(config, "SAP_ICF_URL", None)
    monkeypatch.setattr(config, "SAP_ICF_USERNAME", None)
    monkeypatch.setattr(config, "SAP_ICF_PASSWORD", None)
    with pytest.raises(sap_client.SapConfigError):
        sap_client.post_remnant_simple("SCRAP2-FR", "SBED", "9")


def test_post_remnant_simple_success_builds_minimal_payload(monkeypatch):
    _configure(monkeypatch)
    captured = {}

    def fake_post(url, json, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(200, {"status": "S", "matdoc": "4900012345", "matdoc_year": "2026", "message": "OK"})

    monkeypatch.setattr(sap_client.requests, "post", fake_post)
    result = sap_client.post_remnant_simple("SCRAP2-FR", "SBED", 9)

    assert result["ok"] is True
    assert result["sap_status"] == "S"
    assert result["matdoc"] == "4900012345"
    assert result["matdoc_year"] == "2026"
    # Payload is exactly matnr/sloc/quantity -- nothing from post_remnant's
    # much larger payload (board_length, product_area, precomputed_area, ...)
    # leaks in here.
    assert captured["json"] == {"matnr": "SCRAP2-FR", "sloc": "SBED", "quantity": "9"}
    assert result["payload"] == {"matnr": "SCRAP2-FR", "sloc": "SBED", "quantity": "9"}


def test_post_remnant_simple_non_s_status_is_failure(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(200, {"status": "E", "message": "matnr not found"}),
    )
    result = sap_client.post_remnant_simple("NOT-A-REAL-MATNR", "SBED", "1")
    assert result["ok"] is False
    assert result["sap_status"] == "E"
    assert result["error"] == "matnr not found"


def test_post_remnant_simple_401_is_never_retried(monkeypatch):
    _configure(monkeypatch, retries=3)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _FakeResponse(401)

    monkeypatch.setattr(sap_client.requests, "post", fake_post)
    result = sap_client.post_remnant_simple("SCRAP2-FR", "SBED", "1")
    assert len(calls) == 1
    assert result["ok"] is False
    assert result["error"] == sap_client.FRIENDLY_ERRORS[401]


def test_post_remnant_simple_connection_error_is_retried_up_to_cap(monkeypatch):
    _configure(monkeypatch, retries=2)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        raise sap_client.requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(sap_client.requests, "post", fake_post)
    result = sap_client.post_remnant_simple("SCRAP2-FR", "SBED", "1")
    assert result["ok"] is False
    assert len(calls) == 1 + 2


def test_post_remnant_simple_does_not_affect_post_remnant(monkeypatch):
    """Calling the new function must not mutate any state post_remnant() relies
    on (module-level dicts like FRIENDLY_ERRORS are shared read-only, that's
    fine; this guards against a future edit accidentally coupling the two)."""
    _configure(monkeypatch)
    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(200, {"status": "S", "matdoc": "X", "matdoc_year": "2026"}),
    )
    sap_client.post_remnant_simple("SCRAP2-FR", "SBED", "9")

    monkeypatch.setattr(
        sap_client.requests, "post",
        lambda *a, **k: _FakeResponse(200, {
            "status": "S", "guid": "G1", "area": "10800.000",
            "batch": "0000000243", "bin_zone": "B-1", "message": "OK",
        }),
    )
    result = _call(board_length_cm=240, board_width_cm=120, product_area_cm2=18000, scrap_area_cm2=10800)
    assert result["ok"] is True
    assert result["payload"]["precomputed_area"] == "10800"
    assert "sloc" in result["payload"]  # post_remnant's own payload shape is untouched

"""No-network tests for the Fireworks smoke harness."""

from __future__ import annotations


def test_fireworks_smoke_cost_tracking_records_snapshot(monkeypatch, capsys) -> None:
    import scripts.fireworks_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "fireworks")
    monkeypatch.setattr(smoke, "llm_config_issues", lambda: [])
    monkeypatch.setattr(smoke, "run_text_completion", lambda *_args, **_kwargs: "OK")
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)

    result = smoke.main(["--enable-cost-tracking"])

    captured = capsys.readouterr().out
    assert result == 0
    assert "cost controls preflight ok" in captured
    assert "reduction=80.9%" in captured
    assert "disabled_reduction=0.0%" in captured
    assert "chat smoke ok" in captured
    assert "cost attribution smoke" in captured
    assert '"cost_attribution"' in captured


def test_fireworks_smoke_refuses_incomplete_config(monkeypatch, capsys) -> None:
    import scripts.fireworks_smoke as smoke

    monkeypatch.setattr(smoke, "llm_provider", lambda: "fireworks")
    monkeypatch.setattr(smoke, "llm_config_issues", lambda: ["FIREWORKS_API_KEY is missing"])

    result = smoke.main(["--enable-cost-tracking"])

    captured = capsys.readouterr().out
    assert result == 2
    assert "Fireworks config incomplete" in captured
    assert "cost controls preflight ok" not in captured

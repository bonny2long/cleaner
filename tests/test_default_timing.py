from __future__ import annotations

from cleaner.config import CleanerConfig


def test_default_timing_is_weekly_check_and_30_day_age_gate(monkeypatch) -> None:
    for name in ("MIN_AGE_DAYS", "CHECK_INTERVAL_SECONDS", "DRY_RUN", "DESTRUCTIVE_ACTIONS_ENABLED", "CLEANER_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir("tests")  # no .env here, so built-in defaults apply
    config = CleanerConfig.from_env()
    assert config.min_age_days == 30
    assert config.check_interval_seconds == 7 * 24 * 60 * 60
    assert config.dry_run is True
    assert config.destructive_actions_enabled is False
    assert CleanerConfig().min_age_days == 30

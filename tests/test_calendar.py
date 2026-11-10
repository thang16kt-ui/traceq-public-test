from datetime import datetime, timezone

from worker.calendar import next_run_at


def test_vietnam_schedule_change_and_timezone_recompute():
    now = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)
    schedule = {'local_time':'17:00', 'days_of_week':list(range(7)), 'timezone':'Asia/Ho_Chi_Minh'}
    assert next_run_at(schedule, now) == datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
    schedule['local_time'] = '18:30'
    assert next_run_at(schedule, now) == datetime(2026, 11, 9, 11, 30, tzinfo=timezone.utc)
    schedule['timezone'] = 'Asia/Tokyo'
    assert next_run_at(schedule, now) == datetime(2026, 11, 9, 9, 30, tzinfo=timezone.utc)


def test_monday_zero_and_exact_time_runs_next_eligible_day():
    schedule = {'local_time':'17:00', 'days_of_week':[0], 'timezone':'Asia/Ho_Chi_Minh'}
    now = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)  # Monday 17:00 local
    assert next_run_at(schedule, now) == datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)


def test_nonexistent_dst_wall_time_skips_instead_of_changing_hour():
    schedule = {'local_time':'02:30', 'days_of_week':list(range(7)), 'timezone':'America/New_York'}
    now = datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc)
    assert next_run_at(schedule, now) == datetime(2026, 3, 9, 6, 30, tzinfo=timezone.utc)


def test_ambiguous_dst_wall_time_does_not_schedule_second_fold():
    schedule = {'local_time':'01:30', 'days_of_week':list(range(7)), 'timezone':'America/New_York'}
    now = datetime(2026, 11, 1, 5, 31, tzinfo=timezone.utc)
    assert next_run_at(schedule, now) == datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc)

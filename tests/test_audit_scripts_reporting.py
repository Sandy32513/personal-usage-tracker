from __future__ import annotations

import csv
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import scripts.report_generator as rg
import scripts.weekly_report as wr


UTC = timezone.utc


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_report_generator_helpers_and_main(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_date = date(2026, 3, 17)
    log_dir = tmp_path / "table_logs"
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    (screenshot_dir / "shot1.png").write_text("png", encoding="utf-8")
    (screenshot_dir / "shot2.jpg").write_text("jpg", encoding="utf-8")

    app_rows = [
        {
            "logged_at": "2026-03-17T10:01:00Z",
            "started_at": "2026-03-17T10:00:00Z",
            "ended_at": "2026-03-17T10:30:00Z",
            "duration_seconds": "1800",
            "process_name": "code.exe",
            "app_name": "Visual Studio Code",
            "window_title": "tracker",
        },
        {
            "logged_at": "2026-03-17T10:01:00Z",
            "started_at": "2026-03-17T10:00:00Z",
            "ended_at": "2026-03-17T10:30:00Z",
            "duration_seconds": "1800",
            "process_name": "code.exe",
            "app_name": "Visual Studio Code",
            "window_title": "tracker",
        },
        {
            "logged_at": "2026-03-17T11:01:00Z",
            "started_at": "2026-03-17T11:00:00Z",
            "ended_at": "2026-03-17T11:10:00Z",
            "duration_seconds": "600",
            "process_name": "chrome.exe",
            "app_name": "Google Chrome",
            "window_title": "Search",
        },
    ]
    visit_rows = [
        {
            "logged_at": "2026-03-17T10:05:00Z",
            "visited_at": "2026-03-17T10:05:00Z",
            "browser": "chrome",
            "domain": "google.com",
            "url": "https://www.google.com/search?q=python%20docs",
            "page_title": "python docs",
            "source": "history",
        },
        {
            "logged_at": "2026-03-17T10:07:00Z",
            "visited_at": "2026-03-17T10:07:00Z",
            "browser": "chrome",
            "domain": "github.com",
            "url": "https://github.com/openai/openai-python",
            "page_title": "repo",
            "source": "history",
        },
    ]
    website_rows = [
        {
            "logged_at": "2026-03-17T10:30:00Z",
            "started_at": "2026-03-17T10:00:00Z",
            "ended_at": "2026-03-17T10:30:00Z",
            "duration_seconds": "600",
            "browser": "chrome",
            "domain": "google.com",
            "url": "https://www.google.com/search?q=python%20docs",
            "page_title": "python docs",
            "source": "active_window",
        },
        {
            "logged_at": "2026-03-17T10:45:00Z",
            "started_at": "2026-03-17T10:30:00Z",
            "ended_at": "2026-03-17T10:45:00Z",
            "duration_seconds": "900",
            "browser": "chrome",
            "domain": "youtube.com",
            "url": "https://www.youtube.com/watch?v=abc",
            "page_title": "lofi beats",
            "source": "active_window",
        },
    ]
    media_rows = [
        {
            "logged_at": "2026-03-17T10:20:00Z",
            "started_at": "2026-03-17T10:10:00Z",
            "ended_at": "2026-03-17T10:20:00Z",
            "duration_seconds": "600",
            "source_app": "YouTube Music",
            "title": "Lofi Mix",
            "artist": "Various",
            "playback_state": "playing",
        }
    ]

    write_csv(log_dir / "app_usage.csv", app_rows)
    write_csv(log_dir / "website_visits.csv", visit_rows)
    write_csv(log_dir / "website_usage.csv", website_rows)
    write_csv(log_dir / "media_playback.csv", media_rows)

    project_file = tmp_path / "src" / "tracked.py"
    project_file.parent.mkdir()
    project_file.write_text("print('tracked')", encoding="utf-8")
    modified_ts = datetime(2026, 3, 17, 12, 0, tzinfo=UTC).timestamp()
    os.utime(project_file, (modified_ts, modified_ts))

    app_time = rg.load_app_time(log_dir / "app_usage.csv", target_date)
    website_details = rg.load_website_details(log_dir / "website_visits.csv", target_date)
    website_usage = rg.load_website_usage_time(log_dir / "website_usage.csv", target_date)
    media_usage = rg.load_media_playback_time(log_dir / "media_playback.csv", target_date)
    searches = [rg.extract_search_query(url) for url in website_details["google.com"]]
    searches = [item for item in searches if item]
    modified_files = rg.get_modified_files(tmp_path, target_date)
    session_count = rg.count_app_sessions(log_dir / "app_usage.csv", target_date)

    assert app_time["Visual Studio Code"] == 1800
    assert session_count == 2
    assert website_usage["google.com"] == 600
    assert media_usage[0][0] == "Lofi Mix"
    assert "src\\tracked.py" in modified_files or "src/tracked.py" in modified_files
    assert rg.classify_app("Visual Studio Code") == "productive"
    assert rg.classify_domain("github.com") == "productive"
    assert rg.classify_media("Lofi Mix", "Various", "YouTube", searches) == "productive"

    score, totals = rg.calculate_productivity_score(
        app_time,
        website_usage,
        media_usage,
        searches,
    )
    insights = rg.generate_productivity_insights(
        app_time,
        website_usage,
        media_usage,
        totals,
        searches,
        session_count,
    )
    assert score >= 0
    assert insights

    report_file = tmp_path / "reports" / "daily_report.txt"
    rg.write_report(
        report_file,
        target_date,
        app_time,
        website_details,
        searches,
        modified_files,
        screenshot_dir,
        website_usage,
        media_usage,
        session_count,
    )
    text = report_file.read_text(encoding="utf-8")
    assert "Productivity Score" in text
    assert "python docs" in text
    assert "shot2.jpg" in text

    monkeypatch.setattr(rg, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        rg.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            date="2026-03-17",
            log_dir=str(log_dir),
            project_path=str(tmp_path),
            output=str(tmp_path / "reports" / "main_report.txt"),
        ),
    )
    rg.main()
    assert (tmp_path / "reports" / "main_report.txt").exists()


def test_weekly_report_helpers_and_main(
    tmp_path: Path,
    monkeypatch,
) -> None:
    week_start = date(2026, 3, 16)
    week_end = date(2026, 3, 22)
    log_dir = tmp_path / "table_logs"
    shift_dir = tmp_path / "shift_data"
    shift_dir.mkdir()
    (shift_dir / "shift1.csv").write_text("tiny", encoding="utf-8")

    write_csv(
        log_dir / "app_usage.csv",
        [
            {
                "logged_at": "2026-03-16T09:00:00Z",
                "started_at": "2026-03-16T09:00:00Z",
                "ended_at": "2026-03-16T10:00:00Z",
                "duration_seconds": "3600",
                "process_name": "code.exe",
                "app_name": "Visual Studio Code",
                "window_title": "tracker",
            },
            {
                "logged_at": "2026-03-18T09:00:00Z",
                "started_at": "2026-03-18T09:00:00Z",
                "ended_at": "2026-03-18T10:00:00Z",
                "duration_seconds": "7200",
                "process_name": "chrome.exe",
                "app_name": "Google Chrome",
                "window_title": "docs",
            },
        ],
    )
    write_csv(
        log_dir / "website_usage.csv",
        [
            {
                "logged_at": "2026-03-16T09:30:00Z",
                "started_at": "2026-03-16T09:00:00Z",
                "ended_at": "2026-03-16T09:30:00Z",
                "duration_seconds": "1800",
                "browser": "chrome",
                "domain": "github.com",
                "url": "https://github.com",
                "page_title": "repo",
                "source": "active_window",
            }
        ],
    )
    write_csv(
        log_dir / "media_playback.csv",
        [
            {
                "logged_at": "2026-03-16T09:45:00Z",
                "started_at": "2026-03-16T09:40:00Z",
                "ended_at": "2026-03-16T09:45:00Z",
                "duration_seconds": "300",
                "source_app": "Spotify",
                "title": "Focus Track",
                "artist": "Artist",
                "playback_state": "playing",
            }
        ],
    )

    app_summary = wr.summarize_week(log_dir / "app_usage.csv", week_start, week_end)
    website_summary = wr.summarize_week_websites(log_dir / "website_usage.csv", week_start, week_end)
    media_summary = wr.summarize_week_media(log_dir / "media_playback.csv", week_start, week_end)
    total_duration = wr.total_duration_in_range(log_dir / "app_usage.csv", week_start, week_end)

    assert app_summary["Visual Studio Code"] == 3600
    assert website_summary["github.com"] == 1800
    assert total_duration == 10800
    assert next(iter(media_summary)).startswith("Spotify | Focus Track")
    assert wr.check_shift_data_volume(shift_dir) is False

    monkeypatch.setattr(wr, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("USAGE_TRACKER_SHIFT_DIR", str(shift_dir))
    monkeypatch.setattr(
        wr.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            week_start="2026-03-16",
            log_dir=str(log_dir),
            archive_dir=str(tmp_path / "weekly_archives"),
            output=str(tmp_path / "reports" / "weekly_report.txt"),
            csv_output=str(tmp_path / "reports" / "weekly_report.csv"),
            force=True,
            friday_threshold_hours=20.0,
        ),
    )
    wr.main()

    report_text = (tmp_path / "reports" / "weekly_report.txt").read_text(encoding="utf-8")
    csv_text = (tmp_path / "reports" / "weekly_report.csv").read_text(encoding="utf-8")
    assert "Top Apps" in report_text
    assert "productivity_score" in csv_text

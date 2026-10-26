"""Send matching runs to 52 Card Challenge. No tokens or raw tracks are committed."""
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import sync_strava as source
from utils import load_config, raw_activity_dir

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def running(activity):
    return (activity.get("sport_type") or activity.get("type")) in RUN_TYPES


def local_date(activity):
    return str(activity.get("start_date_local") or "")[:10]


def sample_points(points, limit=12000):
    if len(points) <= limit:
        return points
    step = math.ceil((len(points) - 1) / (limit - 1))
    result = points[::step]
    if result[-1] != points[-1]:
        result.append(points[-1])
    return result


def decode_polyline(encoded):
    result, index, lat, lon = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            value = shift = 0
            while True:
                if index >= len(encoded) or shift > 30:
                    raise ValueError("Invalid route polyline")
                byte = ord(encoded[index]) - 63
                index += 1
                if byte < 0 or byte > 63:
                    raise ValueError("Invalid route polyline")
                value |= (byte & 31) << shift
                shift += 5
                if byte < 32:
                    break
            deltas.append(~(value >> 1) if value & 1 else value >> 1)
        lat += deltas[0]
        lon += deltas[1]
        result.append([lon / 100000, lat / 100000])
    return sample_points(result)


def metrics(activity, athlete_id, basis, points=None):
    preferred = "moving_time" if basis == "moving" else "elapsed_time"
    secondary = "elapsed_time" if basis == "moving" else "moving_time"
    seconds = activity.get(preferred)
    actual_basis = basis
    if not seconds or seconds <= 0:
        seconds = activity.get(secondary)
        actual_basis = "elapsed" if secondary == "elapsed_time" else "moving"
    return {
        "activity_id": str(activity["id"]), "athlete_id": str(athlete_id),
        "sport_type": activity.get("sport_type") or activity.get("type"),
        "date": local_date(activity), "distance_miles": float(activity.get("distance", 0)) / 1609.344,
        "seconds": max(1, round(seconds)) if seconds and seconds > 0 else None,
        "time_basis": actual_basis, "points": points,
        "elevation_gain_m": activity.get("total_elevation_gain"),
    }


def combine_split_run(activities, linked_id):
    """One watch-interrupted outing, still one challenge card and one route."""
    if len(activities) != 2 or any(item.get("points") is None for item in activities):
        return None
    primary = next((item for item in activities if item["activity_id"] == linked_id), activities[0])
    if len({item["time_basis"] for item in activities}) != 1:
        return None
    joined = dict(primary)
    joined["distance_miles"] = sum(item["distance_miles"] for item in activities)
    joined["seconds"] = sum(item["seconds"] for item in activities) if all(item["seconds"] is not None for item in activities) else None
    joined["elevation_gain_m"] = sum(item["elevation_gain_m"] for item in activities) if all(item["elevation_gain_m"] is not None for item in activities) else None
    joined["points"] = sample_points([point for item in activities for point in item["points"]])
    joined["extra_activity_id"] = next(item["activity_id"] for item in activities if item["activity_id"] != primary["activity_id"])
    return joined


class Provider:
    def __init__(self, config):
        self.config = config
        limits = config.get("rate_limits", {})
        self.limiter = source.RateLimiter(
            limits.get("overall_15_min", 200), limits.get("overall_daily", 2000),
            limits.get("read_15_min", 100), limits.get("read_daily", 1000),
            limits.get("safety_buffer", 2), limits.get("min_interval_seconds", 10),
        )
        self.token = source._get_access_token(config, self.limiter)

    def get(self, path, params=None):
        result, self.token = source._run_with_token_refresh(
            self.config, self.token, self.limiter, "challenge import",
            lambda token: source._request_json_with_retry(
                "GET", "https://www.strava.com/api/v3/" + path,
                limiter=self.limiter, request_kind="read",
                headers={"Authorization": "Bearer " + token}, params=params,
            ),
        )
        return result


def site_request(session, method, url, **kwargs):
    response = session.request(method, url, timeout=60, allow_redirects=False, **kwargs)
    if response.status_code not in (200, 207):
        # Never print headers, tokens, payloads or GPS tracks in Actions logs.
        raise RuntimeError("Challenge endpoint returned HTTP " + str(response.status_code))
    return response.json()


def load_activities():
    activities = {}
    normalized = Path("data/activities_normalized.json")
    if normalized.exists():
        for item in json.loads(normalized.read_text(encoding="utf-8")):
            if item.get("source", "strava") == "strava":
                activities[str(item.get("id"))] = item
    for path in Path(raw_activity_dir("strava")).glob("*.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(item, dict) and item.get("id"):
            activities[str(item["id"])] = item
    return activities


def needs_gps(target):
    if target.get("has_route") or target.get("route_opt_out"):
        return False
    checked = target.get("route_checked_at")
    if checked:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(checked.replace("Z", "+00:00"))).total_seconds()
            if elapsed < 21600:
                return False
        except (ValueError, TypeError):
            pass
    return True


def gps_for(provider, activity):
    if activity.get("manual") or activity.get("trainer"):
        return None
    try:
        streams = provider.get("activities/" + str(activity["id"]) + "/streams", {"keys": "latlng", "key_by_type": "true"})
        coords = streams.get("latlng", {}).get("data", []) if isinstance(streams, dict) else []
        if len(coords) >= 2:
            return sample_points([[float(lon), float(lat)] for lat, lon in coords])
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code not in (403, 404):
            raise
    line = (activity.get("map") or {}).get("polyline") or (activity.get("map") or {}).get("summary_polyline")
    return decode_polyline(line) if line else None


def run_export():
    url = os.getenv("CHALLENGE_SYNC_URL", "").strip()
    secret = os.getenv("CHALLENGE_SYNC_SECRET", "")
    if not url and not secret:
        print("52 Card sync is not configured; existing dashboard sync is unchanged.")
        return Counter()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.endswith("/api/strava-sync") or len(secret) < 32:
        raise ValueError("Set a valid HTTPS CHALLENGE_SYNC_URL and a CHALLENGE_SYNC_SECRET of at least 32 characters")
    config = load_config()
    if config.get("source", "strava") != "strava":
        raise ValueError("Challenge export currently supports the Strava source only")
    preview = os.getenv("CHALLENGE_SYNC_PREVIEW", "true").lower() != "false"
    include_private = os.getenv("CHALLENGE_INCLUDE_PRIVATE", "false").lower() == "true"
    basis = os.getenv("CHALLENGE_TIME_BASIS", "moving")
    if basis not in {"moving", "elapsed"}:
        raise ValueError("CHALLENGE_TIME_BASIS must be moving or elapsed")
    budget = max(1, min(20, int(os.getenv("CHALLENGE_MAX_RUNS_PER_SYNC", "6"))))
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + secret})
    setup = site_request(session, "GET", url)
    targets = setup["targets"]
    activities = load_activities()
    provider = Provider(config)
    athlete_id = str(provider.get("athlete")["id"])
    if athlete_id != str(setup["athlete_id"]):
        raise ValueError("Connected Strava account differs from STRAVA_SYNC_ATHLETE_ID on the challenge site")
    # Saved links let us backfill older runs without refetching the full Strava history.
    # Fetch their details only inside the per-job budget below.
    details = {}
    for target in targets:
        identity = target.get("activity_id")
        if identity and identity not in activities and target.get("date"):
            activities[identity] = {"id": identity, "type": "Run", "start_date_local": target["date"] + "T12:00:00"}
    by_date = defaultdict(list)
    for item in activities.values():
        if running(item) and local_date(item) >= setup["start_date"]:
            by_date[local_date(item)].append(item)
    counts = Counter()
    chosen_dates = set()
    # The watch died mid-run on Oct 25. Both public Strava recordings are one outing.
    split_run_dates = {"2026-10-25"}
    for target in sorted(targets, key=lambda row: (row["status"] != "pending", row.get("date") or "")):
        date = target.get("date")
        if not date or date in chosen_dates:
            continue
        if target["status"] == "completed" and target.get("activity_id") and not needs_gps(target):
            continue
        candidates = by_date.get(date, [])
        if not candidates:
            continue
        chosen_dates.add(date)
        if len(candidates) > 10:
            counts["too_many_runs_on_date"] += 1
            continue
        if len(candidates) > budget:
            counts["deferred"] += len(candidates)
            continue
        batch = []
        for summary in candidates:
            identity = str(summary["id"])
            activity = details.get(identity)
            if activity is None:
                try:
                    activity = provider.get("activities/" + identity)
                    details[identity] = activity
                except requests.HTTPError as error:
                    if error.response is not None and error.response.status_code in (403, 404):
                        counts["unavailable_activity"] += 1
                        continue
                    raise
            visibility = activity.get("visibility")
            if not include_private and (activity.get("private") or visibility != "everyone"):
                counts["private_activity_skipped"] += 1
                continue
            if not running(activity) or float(activity.get("distance", 0)) < 16.1:
                counts["non_running_or_short_activity"] += 1
                continue
            coords = gps_for(provider, activity) if needs_gps(target) and (len(candidates) == 1 or identity == target.get("activity_id") or date in split_run_dates) else None
            batch.append(metrics(activity, athlete_id, basis, coords))
        budget -= len(candidates)
        day_count = len(candidates)
        if date in split_run_dates and len(candidates) == 2 and len(batch) == 2 and needs_gps(target):
            combined = combine_split_run(batch, target.get("activity_id"))
            if combined is not None:
                batch = [combined]
                day_count = 1
                counts["split_run_joined"] += 1
        if batch:
            result = site_request(session, "POST", url, json={"activities": batch, "day_count": day_count, "dry_run": preview})
            for item in result["results"]:
                counts[item.get("reason") or item["outcome"]] += 1
                if item.get("route_added"):
                    counts["routes_added"] += 1
        if budget <= 0:
            break
    mode = "PREVIEW (no changes saved)" if preview else "LIVE"
    report = "52 Card sync — " + mode + "\n" + ("\n".join(f"- {key}: {value}" for key, value in sorted(counts.items())) or "- Nothing new to import.")
    print(report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n### " + report + "\n")
    if counts["database_error"]:
        raise RuntimeError("Challenge database rejected an activity; check the migration and run again")
    return counts


if __name__ == "__main__":
    try:
        run_export()
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::warning::52 Card export did not finish: " + message)
        raise SystemExit(1)

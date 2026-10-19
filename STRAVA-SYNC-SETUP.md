# Connect Git Sweaty to your 52 Card Challenge

This update has files for TWO different GitHub repositories. Keep the folders separate:

- `52-card-site/`: copy these files into your **52-Card-Challenge** repository.
- `git-sweaty/`: copy these files into your **git-sweaty** repository.

The connection is built but does not start importing until you add the settings below. It starts in preview mode, which shows what would happen without saving changes. Your existing Strava connection is reused. Do not paste any credentials into chat or commit them in a file.

## 1. Install the Supabase update

1. Open the Supabase project used by your 52-card site.
2. Open **SQL Editor**, then create a **new query**.
3. From `52-card-site/supabase/strava_sync_migration.sql`, copy the entire file into that query.
4. Click **Run**. Wait for Success. This is a new script; do not rerun `schema.sql` or the older migrations.

This adds the importer, duplicate protection, and a private sync log. Existing completed runs retain their saved distance, time, date, notes, and GPS routes.

## 2. Create one shared sync secret

On your Mac, open Terminal and run:

```bash
openssl rand -hex 32
```

Copy the resulting 64-character string somewhere private. You will paste this exact same value into Vercel and GitHub in steps 3 and 5. This is a new connection password, not your Strava password or your Supabase publishable key.

## 3. Add three environment variables to Vercel

Open Vercel, select the **52 Card Challenge** project, then **Settings → Environment Variables**. Add these for **Production**:

| Name | Value |
| --- | --- |
| `CHALLENGE_SYNC_SECRET` | The new 64-character string from step 2 |
| `SUPABASE_SERVICE_ROLE_KEY` | Your Supabase **service_role** key from the project's API keys page, under legacy API keys |
| `STRAVA_SYNC_ATHLETE_ID` | The number at the end of your Strava profile URL |

Your previously supplied profile was `https://www.strava.com/athletes/200753120`, so confirm that it is still your profile and use `200753120` if so.

Keep your existing `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` settings. Do NOT prefix the three new variables with `NEXT_PUBLIC_`. The service_role key is privileged and belongs only in Vercel's server environment; it does not go in Git Sweaty, a public file, or the website's browser code.

## 4. Update the 52-card repository

Copy every file inside `52-card-site/` to the matching location in your existing 52-card project. Replace files when asked and add the new files. Do not add an extra `52-card-site` folder inside the repository.

Commit in GitHub Desktop, then **Push origin**. Wait for Vercel's deployment to show Ready. If you added the environment variables after deploying, redeploy once so that deployment gets the new values.

## 5. Configure the Git Sweaty repository

On GitHub, open **jamoooooooooo/git-sweaty → Settings → Secrets and variables → Actions**.

Under **Secrets**, create these two **repository secrets**:

| Secret | Value |
| --- | --- |
| `CHALLENGE_SYNC_URL` | `https://52-card-challenge.vercel.app/api/strava-sync` |
| `CHALLENGE_SYNC_SECRET` | The exact same 64-character string used in Vercel |

Leave your existing Strava secrets unchanged. You do not need another Strava application or a new Strava connection.

Copy every file inside `git-sweaty/` into the matching location in your existing Git Sweaty repository, including the hidden `.github/workflows/sync.yml` file. Use **Command + Shift + .** in Finder to show hidden folders if needed. Commit and push.

The updated workflow checks approximately every 30 minutes. GitHub scheduled runs are best-effort and can be delayed. A failure in the new challenge export does not stop the original dashboard from publishing.

## 6. Run a preview

1. Open your **git-sweaty** repository on GitHub.
2. Select **Actions → Sync Heatmaps → Run workflow**.
3. Keep the source set to **strava** and do not request a full backfill. Click **Run workflow**.
4. Open the completed run and look at its **52 Card sync** summary or its **Export runs to 52 Card Challenge** step.

It should say **PREVIEW (no changes saved)**. `completed` means an existing pending card would be logged; `linked` means an existing completed run would be connected; `routes_added` means a missing path would be attached. These counts overlap: a completed run can also add a route.

A preview processes up to six candidate runs at a time. It can show the same candidates again because it intentionally saves nothing.

### If your runs are private or followers-only on Strava

The importer defaults to skipping them. If you intentionally want those challenge runs AND their GPS paths published on your public challenge website, go to **Settings → Secrets and variables → Actions → Variables** and add:

```text
CHALLENGE_INCLUDE_PRIVATE = true
```

Rerun the preview afterward. This setting does not change your Strava visibility; it lets this importer publish matching activities to your challenge site. GPS paths uploaded by the importer hide approximately the first and last 0.15 miles for tracks longer than 0.56 miles. This is endpoint trimming, not a geographic privacy zone; loops can pass close to where they started later in the route. No public route is created for activities with no GPS.

## 7. Turn on automatic imports

Once the preview looks right, in the same Git Sweaty **Actions → Variables** settings, add:

```text
CHALLENGE_SYNC_PREVIEW = false
```

Run **Sync Heatmaps** once more. The summary should say **LIVE**. Refresh the 52-card site after it finishes.

You still draw each day's card yourself. The sync only logs a run against an existing card for that same local date. It never invents cards or draws them automatically.

Older missing routes are filled gradually, up to six candidate runs per workflow run. Wait for the next scheduled runs or run the workflow manually again. Existing activity IDs and saved Strava links help match older entries without resetting your dashboard history. A historic date absent from both Git Sweaty's saved history and the challenge's Strava links will need a saved activity link or a Git Sweaty history sync first.

## What happens automatically

- A unique matching run completes the pending card with its actual miles, time, and Strava link.
- By default, **moving time** is used for imported pace, matching the usual Strava running display. The edit form labels an imported moving time accordingly. To use elapsed time instead for future imports, set the optional Actions variable `CHALLENGE_TIME_BASIS` to `elapsed`.
- Run dates use the activity's local date, so a Mexico City run is not shifted to another day using UTC.
- Existing completed runs keep their manually saved stats, even if Strava reports different values.
- Existing uploaded GPS routes are preserved. Removing a route through the challenge site disables automatic GPS imports for that card, so the next sync will not restore it. You can still manually upload a new GPX. Missing paths are obtained from GPS streams, with an available route polyline as fallback, and immediately join Routes and replay after a live import.
- Duplicate imports are harmless. If you later manually edit an automatically imported run, the next sync preserves your edits.
- Ambiguous matches are skipped: multiple runs on an unlinked date, mismatched saved activity links, or changed run dates need manual correction. Linking the correct Strava activity URL to a run establishes an explicit match.

The sync is additive. It does not mirror later Strava edits, privacy changes, or deletions onto entries already saved in the challenge. Edit/remove an imported entry or route on the challenge site when necessary. Imported routes are simplified GPS paths, not archived downloadable GPX files.

## Troubleshooting

- **HTTP 401**: the sync passwords in GitHub and Vercel differ, or the Production environment was not redeployed after changing its password.
- **HTTP 503**: check the three Vercel settings, confirm the new SQL script succeeded, and redeploy.
- **Another athlete**: `STRAVA_SYNC_ATHLETE_ID` does not match the account authorized in Git Sweaty.
- **private_activity_skipped**: review the optional private-activity setting in step 6.
- **multiple_runs_on_date**: edit the challenge run and paste the correct Strava activity URL before retrying. New unlogged cards can also have their URL saved through the existing run form when you log them manually.
- **date_conflict / different_activity_already_linked**: review that run's saved date and Strava link. The importer will not overwrite the conflict.
- **no_card_for_date**: draw or enter the running card first. The next sync can pick up the activity.
- **No routes added**: routes already uploaded are kept; a run with no GPS cannot add a map path. Missing-GPS checks are retried no more frequently than every six hours after a successful link.
- **Backfill progress stops on private or conflicting entries**: resolve the first flagged entries or increase `CHALLENGE_MAX_RUNS_PER_SYNC` temporarily to `20` (the maximum). Restore the default `6` afterward to keep API usage low.
- **Git Sweaty Strava authorization fails**: fix its existing Strava connection first; the new importer reuses that same connection.

To stop imports immediately, set `CHALLENGE_SYNC_PREVIEW` back to `true`. To revoke the connection completely, remove `CHALLENGE_SYNC_SECRET` from Vercel. Both leave saved runs intact.

For a private audit, use Supabase SQL Editor:

```sql
select activity_date, activity_id, outcome, reason, synced_at
from public.run_sync_log
order by synced_at desc;
```

The log is readable only by the challenge administrator and server role, never anonymous visitors. There are no credentials or GPS coordinates in it.

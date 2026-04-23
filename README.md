# MLB close-game alerts — multi-user

Push notification to you and your mates' phones whenever a live MLB game is
close and late: **end of the 7th inning or later, with the score tied or
within a chosen run differential**.

- **For you (admin)**: one public GitHub repo, one private subscribers list on
  your laptop. Run `python manage.py sync` to push. Done.
- **For your mates**: install the ntfy app, pick a topic, text it to you. Done.

No servers, no subscriptions, no monthly fees. Runs on free GitHub Actions,
pushes via free ntfy.sh.

---

## How it works

```
GitHub Actions (every 5 min)
        │
        ▼
   poll.py ──► MLB Stats API
        │
        ▼
   For each subscriber: trigger check (inning >= 7 End AND |diff| <= their_max)
        │
        ▼
   ntfy.sh push to each subscriber's topic ──► their phone
```

Each (subscriber, game) alerts at most once per UTC day. State is committed
back to `state.json` so you've got an audit trail.

---

## Files

```
mlb-alerts/
├── poll.py                 # Main entry. Loops subscribers x games.
├── mlb.py                  # MLB Stats API client.
├── triggers.py             # Pure trigger logic.
├── notify.py               # ntfy push sender.
├── state.py                # Per-subscriber dedup.
├── subscribers.py          # Subscriber parsing + validation.
├── config.py               # Env var config.
├── teams.py                # Team ID → abbreviation map.
├── manage.py               # ADMIN CLI — add/remove mates, sync to GitHub.
├── simulate.py             # Fake close game, end-to-end test.
├── send_test_alert.py      # Ping every subscriber with a test message.
├── check_today.py          # Inspect today's MLB schedule + trigger decision.
├── test_triggers.py        # Unit tests for trigger logic.
├── test_state.py           # Unit tests for state/dedup.
├── test_subscribers.py     # Unit tests for subscriber parsing.
├── subscribers.example.yaml  # Copy this to subscribers.yaml and edit.
├── subscribers.yaml        # Your real list. Gitignored. Source of truth.
├── state.json              # Committed by the workflow each run.
├── FOR_YOUR_MATES.md       # Send this to your mates.
├── requirements.txt
└── .github/workflows/poll.yml
```

---

## Admin setup (first time, ~10 min)

### 1. Prepare the repo

```powershell
# From the mlb-alerts folder on your Windows machine, in VS Code terminal:
python -m pip install -r requirements.txt
cp subscribers.example.yaml subscribers.yaml
```

Edit `subscribers.yaml` in VS Code. Start with just yourself:

```yaml
subscribers:
  - name: mitch
    ntfy_topic: mlb-alerts-xbgog1tjw5qmoqqznovybq
    team_filter: []      # all teams
    max_run_diff: 1
```

### 2. Test locally

```powershell
# Install the ntfy app on your phone, subscribe to the topic above.
python manage.py validate
python send_test_alert.py --only mitch
# You should get a push within seconds.
python simulate.py --send --only mitch
# You should get a "Close MLB game: LAD 5 @ SD 5" alert.
```

### 3. Push to GitHub

1. Create a new **public** GitHub repo (unlimited free Actions).
2. From the folder:

   ```powershell
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/mlb-alerts.git
   git push -u origin main
   ```

3. Install the GitHub CLI if you don't have it: https://cli.github.com
4. Authenticate: `gh auth login` (follow prompts).
5. Sync your subscribers to the repo secret:

   ```powershell
   python manage.py sync
   ```

   This reads `subscribers.yaml` and stores it as the `SUBSCRIBERS_JSON` secret
   in your repo via `gh`. If you don't want to use `gh`, run
   `python manage.py sync --print-only` and paste the JSON into the GitHub
   Secret UI yourself (Settings → Secrets and variables → Actions → New
   repository secret → name: `SUBSCRIBERS_JSON`).

6. Go to the repo's **Actions** tab → enable workflows → click into *MLB
   close-game poller* → **Run workflow**. Watch it run. Green tick = ✅.

From now on, it runs every 5 minutes on its own, 24/7.

---

## Adding a mate (2 min)

1. Send them `FOR_YOUR_MATES.md` (see that file for the guide).
2. They text you their topic + team preferences.
3. On your end:

   ```powershell
   python manage.py add dave --topic dave-topic-they-chose --teams NYY,BOS
   python manage.py sync
   ```

4. Optional: ping them to confirm it works:

   ```powershell
   python send_test_alert.py --only dave
   ```

## Removing a mate

```powershell
python manage.py remove dave
python manage.py sync
```

## Generating a topic for someone

```powershell
python manage.py gen-topic --prefix dave
# prints: dave-xyz9k2p7qj4m...
```

## Inspecting your current list

```powershell
python manage.py list
```

## Validating your file without syncing

```powershell
python manage.py validate
```

---

## Validation tools (use any time)

```powershell
# Set subscriber source for local scripts
$env:SUBSCRIBERS_FILE = "subscribers.yaml"

# Unit tests
python -m unittest test_triggers test_state test_subscribers -v

# Dry-run simulate a close game for all subscribers (no pushes)
python simulate.py

# Real push to all subscribers (proves end-to-end)
python simulate.py --send

# Show today's MLB schedule and what would trigger right now
python check_today.py

# Full poller in dry-run (hits real MLB API, no pushes)
$env:MLB_DRY_RUN = "1"
python poll.py
```

---

## Trigger rules (exact)

A game fires an alert for a subscriber if ALL of these are true:

1. `abstractGameState == "Live"` (not Preview, not Final)
2. `detailedState` doesn't contain "delay"
3. Either `currentInning == 7 AND inningState == "End"`, or `currentInning >= 8`
4. `|home_runs - away_runs| <= subscriber.max_run_diff` (default 1)
5. If subscriber has `team_filter` set, one team is in it

Each (subscriber, gamePk) pair fires at most once per UTC day.

---

## Troubleshooting

- **Workflow failing**: Actions tab → click the run → read the log. Most
  common cause is `SUBSCRIBERS_JSON` secret missing or malformed.
- **A mate isn't getting pings**: `python send_test_alert.py --only their-name`.
  If that lands, their subscriber config is fine. If it doesn't, double-check
  the topic name matches between their phone and your `subscribers.yaml`.
- **GitHub disables the workflow**: happens after 60 days of no commits on
  public repos. During MLB season the state.json commits keep it alive. In
  off-season you might see an email; click re-enable once.
- **ntfy rate limits**: 250 msgs/day per topic, 5 msg/sec burst. Irrelevant
  unless you've got hundreds of subscribers.

---

## Data & terms

Data from MLB's public Stats API (`statsapi.mlb.com`). Personal, non-commercial
use. See MLB's copyright notice at `http://gdx.mlb.com/components/copyright.txt`.

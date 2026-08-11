#!/bin/zsh
# Daily driver. Spec §10: a failed run must never look like a quiet news day.
#
# Install (07:00 IST daily):
#   crontab -e
#   30 1 * * * /Users/tanmayshah/Desktop/Financial\ Tracker/run-daily.sh
#   (01:30 UTC = 07:00 IST; cron uses the machine's local timezone, adjust to taste)

set -uo pipefail

ROOT="${0:A:h}"
cd "$ROOT" || exit 1

LOG="$ROOT/out/run.log"
mkdir -p "$ROOT/out"

# The Chrome profile carrying the X account that owns the List. Without these
# the extractor authenticates as the wrong account.
export TWITTER_BROWSER=chrome
export TWITTER_CHROME_PROFILE=Default

# Optional: enables the prose and vision extraction passes. Without it the run
# degrades to cashtag + keyword matching and says so on the page.
[[ -f "$ROOT/.env" ]] && source "$ROOT/.env"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  # Re-chdir inside the pipeline subshell and use absolute paths. Under launchd
  # the shell inherits a $PWD string whose kernel cwd is not resolvable, so `pwd`
  # looks right while uv's getcwd() fails with "Current directory does not exist".
  cd "$ROOT" || { echo "cannot cd to $ROOT"; exit 1; }
  uv run --project "$ROOT" python "$ROOT/src/run.py"
  STATUS=$?
  echo "exit: $STATUS"
} 2>&1 | tee -a "$LOG"

STATUS=${pipestatus[1]}

if [[ $STATUS -ne 0 ]]; then
  MSG="X Signal Tracker FAILED $(date '+%d %b %H:%M'). Page left untouched. See out/run.log"
  echo "$MSG" >&2
  # Telegram alerting, matching the airdrop bot's pattern. Silent no-op until
  # TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env.
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" -d "text=${MSG}" >/dev/null
  fi
  osascript -e "display notification \"$MSG\" with title \"X Signal Tracker\"" 2>/dev/null
fi

exit $STATUS

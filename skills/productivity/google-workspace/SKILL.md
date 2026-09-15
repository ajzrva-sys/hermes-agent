---
name: google-workspace
description: "Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python."
version: 1.2.0
author: Nous Research
license: MIT
platforms: [linux, macos, windows, freebsd]
required_credential_files:
  - path: google_token.json
    description: Google OAuth2 token (created by setup script)
  - path: google_client_secret.json
    description: Google OAuth2 client credentials (downloaded from Google Cloud Console)
metadata:
  hermes:
    tags: [Google, Gmail, Calendar, Drive, Sheets, Docs, Contacts, Email, OAuth]
    homepage: https://github.com/NousResearch/hermes-agent
    related_skills: [himalaya]
---

# Google Workspace

Gmail, Calendar, Drive, Contacts, Sheets, and Docs — through Hermes-managed OAuth and a thin CLI wrapper. When `gws` is installed, the skill uses it as the execution backend for broader Google Workspace coverage; otherwise it falls back to the bundled Python client implementation.

## References

- `references/gmail-search-syntax.md` — Gmail search operators (is:unread, from:, newer_than:, etc.)
- `references/daily-brief.md` — daily/morning brief procedure: schedule + conflicts + meeting prep + urgent mail from Gmail and Calendar. Load it when the user asks for a morning brief, meeting preparation, or "what's on my calendar and what email needs attention."

## Scripts

- `scripts/setup.py` — OAuth2 setup (run once to authorize)
- `scripts/google_api.py` — compatibility wrapper CLI. It prefers `gws` for operations when available, while preserving Hermes' existing JSON output contract.

## First-Time Setup

Use `terminal` for help/status checks. Authentication belongs in the user's
own interactive terminal/browser, not an agent-captured credential session.
On FreeBSD, use the bundled Python client when `gws` is absent; do not
substitute a Linux binary.

Resolve the active profile's skill directory with `skill_view` first. The
following Bash examples use the bundled category path; substitute the
resolved directory if it differs. Select an absolute native Python path:

```bash
PROFILE_HOME="${HERMES_HOME:-$HOME/.hermes}"
GOOGLE_SCRIPTS="$PROFILE_HOME/skills/productivity/google-workspace/scripts"
GOOGLE_PY="$PROFILE_HOME/tool-envs/google/bin/python"
GSETUP=("$GOOGLE_PY" "$GOOGLE_SCRIPTS/setup.py")
"${GSETUP[@]}" --help
```

On FreeBSD, if the chosen interpreter lacks the exact `REQUIRED_PACKAGES`
from `scripts/setup.py`, create a user-owned environment with a verified
native Python, for example `uv venv --python /usr/local/bin/python3.12
"$PROFILE_HOME/tool-envs/google"` after checking that interpreter exists.
With install approval, run `"${GSETUP[@]}" --install-deps` there; the helper
uses its own exact pins. Never install optional dependencies into the shared
Hermes runtime. A pre-existing interpreter is reusable only if its exact
package versions already satisfy the helper. Even `--check` can install
missing dependencies or refresh a token; it is not an offline-only probe.

### Step 0: Check if already set up

```bash
"${GSETUP[@]}" --check
```

`AUTHENTICATED` confirms token status, not access to every service. Inspect
any partial-scope warning before an approved operation.

### Step 1: Triage — ask the user what they need

Before starting OAuth setup, ask the user TWO questions:

**Question 1: "What Google services do you need? Just email, or also
Calendar/Drive/Sheets/Docs?"**

- **Email only** → Consider `himalaya` if the account supports IMAP and an
  approved authentication method (an App Password is not available on every
  Google account). It does not require a Google Cloud project for password auth.
- **Workspace services** → Review the helper's fixed `SCOPES` before consent:
  Gmail read/send/modify, Calendar, Drive, Contacts read, Sheets, and Docs.
  This includes write access even when the intended task is read-only.
  `setup.py` does not implement `--services` or `--format`; there is no
  narrower service-selection flag. If the requested scope set is unacceptable,
  record `blocked-scopes`. Do not silently broaden access or remove scope
  validation. Partial consent may leave some operations unavailable.

**Question 2: "Does your Google account use Advanced Protection (hardware
security keys required to sign in)? If you're not sure, you probably don't
— it's something you would have explicitly enrolled in."**

- **No / Not sure** → Normal setup. Continue below.
- **Yes** → Their Workspace admin must add the OAuth client ID to the org's
  allowed apps list before Step 4 will work. Let them know upfront.

### Step 2: Create OAuth credentials (one-time, ~5 minutes)

Tell the user:

> You need a Google Cloud OAuth client. This is a one-time setup:
>
> 1. Create or select a project:
>    https://console.cloud.google.com/projectselector2/home/dashboard
> 2. Enable the required APIs from the API Library:
>    https://console.cloud.google.com/apis/library
>    Enable: Gmail API, Google Calendar API, Google Drive API,
>    Google Sheets API, Google Docs API, People API
> 3. Create the OAuth client here:
>    https://console.cloud.google.com/apis/credentials
>    Credentials → Create Credentials → OAuth 2.0 Client ID
> 4. Application type: "Desktop app" → Create
> 5. If the app is still in Testing, add the user's Google account as a test user here:
>    https://console.cloud.google.com/auth/audience
>    Audience → Test users → Add users
> 6. Download the JSON file and tell me the file path
>
> Important Hermes CLI note: if the file path starts with `/`, do NOT send only the bare path as its own message in the CLI, because it can be mistaken for a slash command. Send it in a sentence instead, like:
> `The JSON file path is: ~/Downloads/client_secret_....json`

Once they provide the path:

```bash
"${GSETUP[@]}" --client-secret /path/to/client_secret.json
```

Ask only for the file path, never raw client secrets in chat. The user keeps
the downloaded credential file private on the target host; do not copy a Mac
token, keychain, or another profile's credentials to satisfy setup.

### Step 3: Get authorization URL

After scope approval, the user runs this in their own terminal:

```bash
"${GSETUP[@]}" --auth-url
```

It prints a plain URL, not a JSON `auth_url` object, and stores pending PKCE
state in the active profile's `google_oauth_pending.json`. It does not write
`google_oauth_last_url.txt`. After browser consent the redirect to
`http://localhost:1` normally fails to load; that is expected. The redirected
URL contains a credential and must stay out of chat and logs.

For `Error 403: access_denied`, check the test-user list at
https://console.cloud.google.com/auth/audience and the account's app policy.

### Step 4: Exchange the code

The helper accepts `--auth-code` with either the redirect URL or raw code,
using the pending session from Step 3. It has no masked CLI input. Do not
collect the code in chat or place it in agent tool arguments, command history,
or logs. Completion must use a user-owned secure flow outside the captured
agent session; if no such flow is available, record `blocked-auth` rather
than automating a secret-bearing command.

On expired/reused codes or a state mismatch, the helper prints an error.
It does not return `fresh_auth_url`; the user must restart `--auth-url` and
use the newest session only.

### Step 5: Verify

```bash
"${GSETUP[@]}" --check
# Only with approval for a live Calendar API read:
"${GSETUP[@]}" --check-live
```

`--check-live` lists at most one calendar and should print `LIVE_CHECK_OK`.
Then verify one approved read-only operation against the intended account.
Token refresh is automatic; successful login does not authorize writes.

### Notes

- Token is stored at `$PROFILE_HOME/google_token.json` and auto-refreshes.
- Pending OAuth state/verifier are stored at `$PROFILE_HOME/google_oauth_pending.json` until exchange completes. Keep these files private; never include their contents in receipts.
- If `gws` is installed, `google_api.py` uses the same profile-scoped credentials. A separate `gws auth login` is not needed.
- With user approval, revoke using `"${GSETUP[@]}" --revoke`.

## Usage

All commands go through the API script. Set `GAPI` as a shorthand:

```bash
GAPI=("$GOOGLE_PY" "$GOOGLE_SCRIPTS/google_api.py")
```

Use `"${GAPI[@]}"` for each API invocation below, in the same Bash shell as
these definitions. Re-establish them in a new terminal process; do not rely
on venv activation or alter the shared launcher's interpreter.

### Gmail

```bash
# Search (returns JSON array with id, from, subject, date, snippet)
"${GAPI[@]}" gmail search "is:unread" --max 10
"${GAPI[@]}" gmail search "from:boss@company.com newer_than:1d"
"${GAPI[@]}" gmail search "has:attachment filename:pdf newer_than:7d"

# Read full message (returns JSON with body text)
"${GAPI[@]}" gmail get MESSAGE_ID

# Send
"${GAPI[@]}" gmail send --to user@example.com --subject "Hello" --body "Message text"
"${GAPI[@]}" gmail send --to user@example.com --subject "Report" --body "<h1>Q4</h1><p>Details...</p>" --html
"${GAPI[@]}" gmail send --to user@example.com --subject "Hello" --from '"Research Agent" <user@example.com>' --body "Message text"

# Reply (automatically threads and sets In-Reply-To)
"${GAPI[@]}" gmail reply MESSAGE_ID --body "Thanks, that works for me."
"${GAPI[@]}" gmail reply MESSAGE_ID --from '"Support Bot" <user@example.com>' --body "Thanks"

# Labels
"${GAPI[@]}" gmail labels
"${GAPI[@]}" gmail modify MESSAGE_ID --add-labels LABEL_ID
"${GAPI[@]}" gmail modify MESSAGE_ID --remove-labels UNREAD
```

### Calendar

```bash
# List events (defaults to next 7 days)
"${GAPI[@]}" calendar list
"${GAPI[@]}" calendar list --start 2026-03-01T00:00:00Z --end 2026-03-07T23:59:59Z

# Create event (ISO 8601 with timezone required)
"${GAPI[@]}" calendar create --summary "Team Standup" --start 2026-03-01T10:00:00-06:00 --end 2026-03-01T10:30:00-06:00
"${GAPI[@]}" calendar create --summary "Lunch" --start 2026-03-01T12:00:00Z --end 2026-03-01T13:00:00Z --location "Cafe"
"${GAPI[@]}" calendar create --summary "Review" --start 2026-03-01T14:00:00Z --end 2026-03-01T15:00:00Z --attendees "alice@co.com,bob@co.com"

# Delete event
"${GAPI[@]}" calendar delete EVENT_ID
```

### Drive

```bash
# Search existing files
"${GAPI[@]}" drive search "quarterly report" --max 10
"${GAPI[@]}" drive search "mimeType='application/pdf'" --raw-query --max 5

# Get metadata for a single file
"${GAPI[@]}" drive get FILE_ID

# Upload a local file (auto-detects MIME type)
"${GAPI[@]}" drive upload /path/to/report.pdf
"${GAPI[@]}" drive upload /path/to/image.png --name "Logo.png" --parent FOLDER_ID

# Download (binary files download as-is; Google-native files export to a
# sensible default — Docs→pdf, Sheets→csv, Slides→pdf, Drawings→png)
"${GAPI[@]}" drive download FILE_ID
"${GAPI[@]}" drive download DOC_ID --output ~/doc.pdf
"${GAPI[@]}" drive download DOC_ID --export-mime text/plain --output ~/doc.txt

# Create a folder
"${GAPI[@]}" drive create-folder "Reports"
"${GAPI[@]}" drive create-folder "Q4" --parent FOLDER_ID

# Share
"${GAPI[@]}" drive share FILE_ID --email alice@example.com --role reader
"${GAPI[@]}" drive share FILE_ID --email alice@example.com --role writer --notify
"${GAPI[@]}" drive share FILE_ID --type anyone --role reader        # anyone with link
"${GAPI[@]}" drive share FILE_ID --type domain --domain example.com --role reader

# Delete — defaults to trash (reversible). Use --permanent to skip the trash.
"${GAPI[@]}" drive delete FILE_ID
"${GAPI[@]}" drive delete FILE_ID --permanent
```

### Contacts

```bash
"${GAPI[@]}" contacts list --max 20
```

### Sheets

```bash
# Create a new spreadsheet
"${GAPI[@]}" sheets create --title "Q4 Budget"
"${GAPI[@]}" sheets create --title "Inventory" --sheet-name "Stock"

# Read
"${GAPI[@]}" sheets get SHEET_ID "Sheet1!A1:D10"

# Write
"${GAPI[@]}" sheets update SHEET_ID "Sheet1!A1:B2" --values '[["Name","Score"],["Alice","95"]]'

# Append rows
"${GAPI[@]}" sheets append SHEET_ID "Sheet1!A:C" --values '[["new","row","data"]]'
```

### Docs

```bash
# Read (a tabbed Doc returns a "tabs" array; single-tab and legacy Docs also return "body")
"${GAPI[@]}" docs get DOC_ID
"${GAPI[@]}" docs get DOC_ID --tab TAB_ID     # read one tab of a tabbed Doc

# Create a new Doc (optionally seeded with body text)
"${GAPI[@]}" docs create --title "Meeting Notes"
"${GAPI[@]}" docs create --title "Draft" --body "First paragraph..."

# Append text to the end of an existing Doc
"${GAPI[@]}" docs append DOC_ID --text "Additional content to append"
"${GAPI[@]}" docs append DOC_ID --tab TAB_ID --text "..."   # --tab required when the Doc has multiple tabs
```

## Output Format

API commands return JSON; setup commands print status text or a plain URL.
Parse API output with `jq` or read directly. Key fields:

- **Gmail search**: `[{id, threadId, from, to, subject, date, snippet, labels}]`
- **Gmail get**: `{id, threadId, from, to, subject, date, labels, body}`
- **Gmail send/reply**: `{status: "sent", id, threadId}`
- **Calendar list**: `[{id, summary, start, end, location, description, htmlLink}]`
- **Calendar create**: `{status: "created", id, summary, htmlLink}`
- **Drive search**: `[{id, name, mimeType, modifiedTime, webViewLink}]`
- **Drive get**: `{id, name, mimeType, modifiedTime, size, webViewLink, parents, owners}`
- **Drive upload**: `{status: "uploaded", id, name, mimeType, webViewLink}`
- **Drive download**: `{status: "downloaded", id, name, path, mimeType}`
- **Drive create-folder**: `{status: "created", id, name, webViewLink}`
- **Drive share**: `{status: "shared", permissionId, fileId, role, type}`
- **Drive delete**: `{status: "trashed" | "deleted", fileId, permanent}`
- **Contacts list**: `[{name, emails: [...], phones: [...]}]`
- **Sheets get**: `[[cell, cell, ...], ...]`
- **Sheets create**: `{status: "created", spreadsheetId, title, spreadsheetUrl}`
- **Docs create**: `{status: "created", documentId, title, url}`
- **Docs append**: `{status: "appended", documentId, inserted_at, characters}`

## Rules

1. **Never send email, create/delete calendar events, delete Drive files, share files, or modify Docs/Sheets without confirming with the user first.** Show what will be done (recipients, file IDs, content, share role) and ask for approval. For `drive delete`, prefer the default trash (reversible) over `--permanent`.
2. **Check auth before first use** — run `setup.py --check`. If it fails, guide the user through setup.
3. **Use the Gmail search syntax reference** for complex queries — load it with `skill_view("google-workspace", file_path="references/gmail-search-syntax.md")`.
4. **Calendar times must include timezone** — always use ISO 8601 with offset (e.g., `2026-03-01T10:00:00-06:00`) or UTC (`Z`).
5. **Respect rate limits** — avoid rapid-fire sequential API calls. Batch reads when possible.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `NOT_AUTHENTICATED` | Run setup Steps 2-5 above |
| `REFRESH_FAILED` | Token revoked or expired — redo Steps 3-5 |
| `HttpError 403: Insufficient Permission` | Check the operation's required scope with the user; record `blocked-scopes` if not approved. Do not revoke or broaden consent automatically. |
| `AUTHENTICATED (partial)` or "Token missing scopes" | Token status alone does not prove service access. Review missing scopes and repeat consent only with user approval. |
| `HttpError 403: Access Not Configured` | API not enabled — user needs to enable it in Google Cloud Console |
| `ModuleNotFoundError` | With install approval, run `"${GSETUP[@]}" --install-deps` in the user-owned environment, not the shared Hermes runtime. |
| Advanced Protection blocks auth | Workspace admin must allowlist the OAuth client ID |

## Revoking Access

```bash
"${GSETUP[@]}" --revoke
```

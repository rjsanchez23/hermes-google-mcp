# Hermes Google MCP

Personal MCP server that gives a locally-hosted AI agent access to **your own** Google
account: Gmail, Google Calendar and Google Drive.

It is not a service. There is no account, no signup, and no server on the internet. The
process runs on your own machine and talks directly to Google's APIs.

## What it actually asks for

These are the exact OAuth scopes requested at authorization time. Nothing beyond this list
is requested, and each line is the reason it exists.

| Scope | Why |
| --- | --- |
| `gmail.readonly` | Read your mail: search, list labels, open a message |
| `gmail.compose` | Create drafts, so you review before anything is sent |
| `gmail.send` | Send mail on request |
| `calendar` | Read and create calendar events |
| `drive.readonly` | Read-only. **Writing to Drive is deliberately not requested.** |

Drive is read-only on purpose. Deleting or overwriting files is the most destructive thing
an agent can do in your Google account, and this tool does not need it. If you want it, add
`https://www.googleapis.com/auth/drive` to `SCOPES` in `gauth.py` and re-authorize — the
restriction is a design decision, not a limitation of the API.

## Where your data goes

**Nowhere.** That is the whole point of running it locally.

- The OAuth token is stored in `credentials/token.json`, permissions `600`, on the same
  machine that runs the agent.
- Mail, calendar and file contents are read into memory, used for the task at hand, and
  returned to the agent process. They are not written to disk, not logged, and not sent to
  any third party.
- There is no analytics, no telemetry, no crash reporting and no outbound connection other
  than to `*.googleapis.com`.
- If you run it with the optional Composio connection, that changes: Composio becomes a
  middleman. This server exists so you don't have to.

## Installing

Requires Python 3.9+. **No third-party packages** — standard library only, so there is no
`pip install`, no virtualenv and no dependency to audit.

```bash
git clone https://github.com/rjsanchez23/hermes-google-mcp
cd hermes-google-mcp
mkdir -p credentials && chmod 700 credentials
```

1. In Google Cloud, enable **Gmail API**, **Google Calendar API** and **Google Drive API**.
2. Set the OAuth consent screen to **Production** (in Testing, Google expires refresh
   tokens after 7 days).
3. Create an OAuth client of type **Desktop app** and drop the JSON into
   `credentials/client_secret.json`, `chmod 600`.
4. Authorize once:

```bash
python3 setup_oauth.py --start
```

It prints a URL, you authorize in your browser, and the token is saved. No codes to copy.
`python3 setup_oauth.py --status` shows the current state.

## Tools

Fourteen, with fixed names — no dynamic discovery. Small local models handle a fixed list
much better than a menu that changes per call.

```
gmail_list_labels        gmail_create_draft      calendar_list_events
gmail_search             gmail_send_email        calendar_find_free_slots
gmail_get_email          gmail_trash_email       calendar_create_event
gmail_list_drafts                                 calendar_delete_event
                         drive_search_files      drive_read_file
                         drive_list_folder
```

Write operations (`gmail_send_email`, `gmail_trash_email`, `calendar_create_event`,
`calendar_delete_event`) are described in the MCP catalogue as requiring explicit user
confirmation first, and `gmail_create_draft` is the recommended path for anything that
would send mail.

## A note on the calendar and timezones

Everything in the calendar is Europe/Madrid, enforced in code rather than by convention.
Madrid alternates between `+02:00` in summer and `+01:00` in winter, so a hardcoded offset
would silently be an hour wrong for half the year. `zoneinfo.ZoneInfo("Europe/Madrid")` is
used instead, and `calendar_create_event` **rejects** any timestamp whose offset does not
match Madrid's offset on that date, with an error message saying which one to use.

## Revoking access

Revoke it here: <https://myaccount.google.com/permissions> — the entry will be listed as
**Hermes Pi5**. Revoking takes effect immediately, and you can also delete
`credentials/token.json` to drop the local copy.

Note that revoking requires re-authorizing from scratch, and the project id in
`client_secret.json` stays valid until you delete the OAuth client in Google Cloud.

## License

MIT. Use it, change it, run it on your own hardware.

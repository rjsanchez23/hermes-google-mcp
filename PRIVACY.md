# Privacy Policy

**Last updated:** 2026-09-25

## Summary

This is a self-hosted tool. The operator is the only user, and their Google data does not
leave their own machine.

## What is collected

Nothing is collected by the operator or by any third party. The project has no analytics,
no telemetry, no usage tracking, no cookies, and no server component.

## What is accessed

The tool reads and writes **the operator's own Google account**, limited to these scopes,
which are the complete list requested at authorization:

- `gmail.readonly` — read mail
- `gmail.compose` — create drafts
- `gmail.send` — send mail
- `calendar` — read and write calendar events
- `drive.readonly` — read files (no write access to Drive is requested)

No other Google service is touched.

## Where data goes

- **Local storage.** The OAuth access token and refresh token are stored in
  `credentials/token.json` with filesystem permissions `600`, on the machine running the
  tool. Refresh tokens are long-lived credentials; anyone who can read that file can act as
  the operator against the scopes listed above.
- **Ephemeral.** Email bodies, calendar events and file contents are read into memory for
  the duration of a task. They are not written to disk, not logged, and not cached.
- **Network.** The only outbound requests are to Google's own API endpoints
  (`*.googleapis.com`, `oauth2.googleapis.com`) to perform the operations you ask for.

## Third parties

None. There is no analytics vendor, no error-reporting service, and no intermediary service
that handles your data.

If you choose to run this alongside a hosted integration provider such as Composio, **that
provider becomes an additional party** able to see requests and responses. That is a
property of that provider, not of this project, and it is the main reason this project
exists: to keep the path between the agent and Google direct.

## Sharing

Nothing is shared. There is no mechanism in the code to transmit data anywhere.

## Retention

The token file persists until you delete it or revoke access. Message and event contents
are not retained after use.

## Your rights and controls

- **Revoke access:** <https://myaccount.google.com/permissions> — find **Hermes Pi5**. Takes
  effect immediately.
- **Delete the local copy:** remove `credentials/token.json` and `credentials/client_secret.json`.
- **Stop all access:** revoke the OAuth client in Google Cloud, which also invalidates the
  `client_id` in the client file.

## Children

Not directed at children and not intended for use by them.

## Changes

Material changes will be reflected in the `Last updated` date above. Because this is a
self-hosted tool, the version you run is the version on your disk; the authoritative copy is
the repository at the time you installed it.

## Contact

Ricardo Sánchez Estévez — <rjsemaga@gmail.com>

## Additional note on the risk of an AI agent acting on your data

This tool gives a language model programmatic access to your mail and calendar. The model
reads untrusted content: email bodies and calendar invitations are written by third parties
and can contain text crafted to look like instructions. Treat everything read from these
services as data, never as commands. A privacy policy cannot describe or mitigate that risk;
it is a property of giving any agent this access, and it is the main reason to keep Drive
read-only, prefer drafts over sending, and review what the agent proposes before it acts.

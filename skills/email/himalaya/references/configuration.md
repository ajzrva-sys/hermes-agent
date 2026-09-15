# Himalaya Configuration Reference

Configuration file location: `~/.config/himalaya/config.toml`

## Minimal IMAP + SMTP Setup

```toml
[accounts.default]
email = "user@example.com"
display-name = "Your Name"
default = true

# IMAP backend for reading emails
backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "user@example.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"

# SMTP backend for sending emails
message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "user@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"

# Folder aliases — required whenever server folder names differ
# from himalaya's canonical names. See "Folder Aliases" below.
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "Sent"
folder.aliases.drafts = "Drafts"
folder.aliases.trash = "Trash"
```

## Password Options

Do not put plaintext passwords in TOML, chat, command arguments, or logs.
The examples below assume the user has provisioned the secret store outside
the agent session. Never execute the configured password command directly
through an agent tool: its stdout is a secret intended only for Himalaya.

### Password from command (recommended)

```toml
backend.auth.cmd = "pass show email/imap"
```

On FreeBSD, verify that `pass` (or the chosen supported secret command)
exists and can unlock in the user's session. Do not assume a desktop keyring
or copy Mac credentials. If no secure provider is configured, stop at
`blocked-auth` and have the user complete setup in their own terminal.

macOS-only alternative, configured by the user for an existing Keychain item:

```toml
backend.auth.cmd = "security find-generic-password -a user@example.com -s imap -w"
```

`security` is not a FreeBSD command; this is not a migration fallback.

### System keyring (requires keyring feature)

```toml
backend.auth.keyring = "imap-example"
```

The user runs `himalaya account configure <account>` in their own interactive
terminal to store the password. Verify that the selected build and host
actually support the keyring backend; do not assume it on headless FreeBSD.

## Gmail Configuration

```toml
[accounts.gmail]
email = "you@gmail.com"
display-name = "Your Name"
default = true

backend.type = "imap"
backend.host = "imap.gmail.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@gmail.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show google/app-password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.gmail.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@gmail.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show google/app-password"

# Gmail folder mapping. Without these, save-to-Sent fails after
# SMTP delivery succeeds (Gmail's Sent folder is `[Gmail]/Sent Mail`,
# not `Sent`), and `himalaya message send` exits non-zero. Any
# caller that retries on that error will re-run SMTP — duplicate
# emails to recipients. Always include this block for Gmail.
folder.aliases.inbox = "INBOX"
folder.aliases.sent = "[Gmail]/Sent Mail"
folder.aliases.drafts = "[Gmail]/Drafts"
folder.aliases.trash = "[Gmail]/Trash"
```

**Note:** Gmail requires an App Password if 2FA is enabled.

## iCloud Configuration

```toml
[accounts.icloud]
email = "you@icloud.com"
display-name = "Your Name"

backend.type = "imap"
backend.host = "imap.mail.me.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "you@icloud.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show icloud/app-password"

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.mail.me.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "you@icloud.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show icloud/app-password"
```

**Note:** Generate an app-specific password at appleid.apple.com

## Folder Aliases

Map himalaya's canonical folder names (`inbox`, `sent`, `drafts`,
`trash`) to whatever the server actually calls them. Use the
v1.2.0 `folder.aliases.X` syntax (plural, dotted keys, directly
under `[accounts.NAME]`):

```toml
[accounts.default]
# ... other account config ...

folder.aliases.inbox = "INBOX"
folder.aliases.sent = "Sent"
folder.aliases.drafts = "Drafts"
folder.aliases.trash = "Trash"
```

The equivalent TOML sub-section form also works in v1.2.0:

```toml
[accounts.default.folder.aliases]
inbox = "INBOX"
sent = "Sent"
drafts = "Drafts"
trash = "Trash"
```

> **Don't use the singular `alias` form.** Pre-v1.2.0 docs showed
> `[accounts.NAME.folder.alias]` (singular). v1.2.0 silently
> ignores that sub-section — TOML parses without error, but the
> alias resolver never reads it. Every lookup then falls through
> to the canonical name. On Gmail (where `sent` is actually
> `[Gmail]/Sent Mail`) this means save-to-Sent fails *after* SMTP
> delivery succeeds, and `himalaya message send` exits non-zero.
> Any caller (agent, script, user) that retries on that error
> code will re-run the send — including SMTP — producing duplicate
> emails to recipients. Always use `folder.aliases.X` (plural).

## Multiple Accounts

```toml
[accounts.personal]
email = "personal@example.com"
default = true
# ... backend config ...

[accounts.work]
email = "work@company.com"
# ... backend config ...
```

Switch accounts with `--account`:

```bash
himalaya --account work envelope list
```

## Notmuch Backend (local mail)

```toml
[accounts.local]
email = "user@example.com"

backend.type = "notmuch"
backend.db-path = "~/.mail/.notmuch"
```

## OAuth2 Authentication (for providers that support it)

```toml
backend.auth.type = "oauth2"
backend.auth.client-id = "your-client-id"
backend.auth.client-secret.cmd = "pass show oauth/client-secret"
backend.auth.access-token.cmd = "pass show oauth/access-token"
backend.auth.refresh-token.cmd = "pass show oauth/refresh-token"
backend.auth.auth-url = "https://provider.com/oauth/authorize"
backend.auth.token-url = "https://provider.com/oauth/token"
```

## Additional Options

### Signature

```toml
[accounts.default]
signature = "Best regards,\nYour Name"
signature-delim = "-- \n"
```

### Downloads directory

```toml
[accounts.default]
downloads-dir = "~/Downloads/himalaya"
```

### Editor for composing

Set via environment variable:

```bash
export EDITOR="vim"
```

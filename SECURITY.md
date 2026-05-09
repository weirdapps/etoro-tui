# Security Policy

## Scope

**etoro-tui is a personal portfolio dashboard.** Single-user, runs locally on your machine, talks to the eToro Public API over HTTPS. It is **not** a security-audited product.

The eToro Public API endpoints used are **read-only**:

- `GET /api/v1/trading/info/portfolio`
- `GET /api/v1/market-data/instruments/rates`

The app **never** sends trade orders, never deposits, never withdraws, never modifies your eToro account. A leaked API key grants an attacker visibility into your portfolio composition, equity, cash, and P&L history — but not the ability to trade on your behalf.

When you generate the API key, set permission to **Read** (not Write). etoro-tui has no need for Write.

## Supported versions

Only the latest minor release receives security fixes.

| Version | Supported |
|---|---|
| 0.2.x   | ✅ |
| < 0.2   | ❌ |

## Reporting a vulnerability

Please report security issues **privately** rather than opening a public GitHub issue.

- **Preferred**: open a [GitHub Security Advisory](https://github.com/weirdapps/etoro-tui/security/advisories/new) on the repo.
- **Alternative**: contact the maintainer directly via the email on the GitHub profile.

Please include:

- A description of the issue and its impact
- Steps to reproduce, or a proof of concept
- Any suggested mitigation

You should receive an acknowledgment within **7 days**. If the issue is confirmed, a fix will land in the next patch release; you'll be credited in the advisory unless you'd rather stay anonymous.

## What's in scope

- Credential leakage paths (logs, error messages, file permissions, git history)
- Local privilege escalation via the snapshot DB or `~/.etoro-tui/.env`
- HTTPS / TLS bypass or downgrade
- Code execution via crafted TOML config, census JSON, or signals CSV
- Dependency vulnerabilities that affect the installed surface

## What's out of scope

- **The eToro Public API itself** — report issues to eToro directly
- **Census / signals data sources** (`weirdapps/etoro_census`, `weirdapps/etorotrade`) — report issues on those repos
- Trading losses, market data errors, or any financial decision made based on numbers shown by this tool — see the disclaimer in `README.md`
- Issues requiring physical access to your machine
- Issues requiring an attacker to already control your terminal session, shell, or user account

## Known limitations

These are documented rather than secret:

- **Windows file permissions**: the `chmod 0o600` calls applied to `~/.etoro-tui/.env`, `snapshots.db`, and `etoro-tui.log` are POSIX-specific. Windows NTFS does not honor POSIX modes; Windows users should rely on user-account isolation, ACLs, or the system keyring instead of the `.env` file.
- **No certificate pinning**: HTTPS validation uses the system CA bundle. A trusted-CA MITM (corporate proxy, malicious system-level CA) could intercept requests. This is the standard HTTPS-client trust model.
- **Keyring is shared with all locally-installed apps**: any Python package you install can read the same OS keyring entries that etoro-tui writes. Standard keyring caveat.
- **Single-maintainer**: bus factor 1. No third-party code review.
- **Not penetration-tested**.
- **No SLSA provenance / signed releases** on PyPI.

If your threat model requires any of these protections, **do not run etoro-tui in that environment**.

## Security-sensitive build/release notes (for maintainers)

- Release tags should be signed with `git tag -s`.
- PyPI uploads should use a token scoped to this project only.
- Keep `Dependabot` enabled; review every PR before merge.
- Run `pip-audit` (CI does this automatically) before each release.
- Never commit `.env`, `*.envfile`, or any file containing real keys. The `.gitignore` defends against this but human review is the last line.

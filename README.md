# Home Assistant Better Stack

Custom Home Assistant integration that sends error events to Better Stack Errors using its Sentry-compatible DSN. Requires Home Assistant **2026.10.0 or newer**. It does not enable performance tracing or Better Stack log ingestion, and creates no entities.

## Install with Marketplace

The built-in Marketplace is available starting with Home Assistant **2026.11**. On 2026.10, use HACS with the same repository and the **Integration** category. See [Home Assistant's Marketplace guide](https://contributors.home-assistant.io/marketplace/how-it-works/).

[![Open the repository in Marketplace or HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=haveyourphil&repository=homeassistant-betterstack&category=integration)

1. Open the link above, or add `https://github.com/haveyourphil/homeassistant-betterstack` as a custom repository, category **Integration**, in Marketplace/HACS. A GitHub connection is required for custom repositories.
2. Download **Better Stack**. Restart Home Assistant if requested. Updates to already loaded integration code require a restart.
3. For a **new installation**, go to **Settings > Devices & services > Add integration > Better Stack**.
4. Paste the Sentry-compatible DSN from your Better Stack Errors application's **Data ingestion** page. The expected format is `https://APPLICATION_TOKEN@INGESTING_HOST/APPLICATION_ID`.

### Switching from a manual installation

Back up your Home Assistant configuration, then download this repository through Marketplace/HACS and restart Home Assistant. It replaces the code in `custom_components/betterstack` while retaining the existing **Better Stack** config entry, DSN, unique ID, and options. **Do not delete the integration from Devices & services or add it again.** No config-entry migration is needed, and no user data is stored in the code directory.

Only one repository can manage the `betterstack` domain. If another fork already manages it in Marketplace/HACS, remove that repository's download before switching, keep the Devices & services entry, and install this one before restarting.

### Manual installation

Download a release and copy its `custom_components/betterstack` folder into your Home Assistant configuration's `custom_components` directory. Restart Home Assistant, then configure it as above if it is a new installation.

## Options

Open **Settings > Devices & services > Better Stack > Configure** to choose whether to send:

- Handled exceptions (including SDK events marked as handled) and events tagged `handled: yes`.
- Events from custom integrations.
- Events from third-party Python packages.

All three default to off. **Changes apply immediately to subsequent events**; no reload or restart is needed. ERROR and CRITICAL log events are eligible; lower logging levels are not collected as events or breadcrumbs. The integration's own errors are excluded to avoid feedback loops.

## Data sent

Events can include error messages, stack traces, Python package versions, the Home Assistant version/release channel, installation type, system/software versions, and installed integration names. Home Assistant's existing installation UUID is sent as the user ID and a tag, so events from the same installation can be grouped; this is a persistent pseudonymous identifier.

`send_default_pii` is disabled. It excludes the OS username and timezone from its system metadata, removes the SDK hostname, inherited user details, HTTP request details and command-line arguments, and disables stack-frame locals and breadcrumbs. It redacts its configured DSN and its keys from event fields and removes credentials from HTTP(S) URLs. Error messages and exception text supplied by other code may still contain personal information or unrelated secrets; these controls cannot guarantee anonymization of arbitrary logs.

The DSN and options remain in Home Assistant's config-entry storage, outside the integration folder. Treat the DSN and your backups as credentials. Nothing needs a `persistent_directory`.

## Troubleshooting

- **Invalid or rotated DSN:** use the entry menu's **Reconfigure** action to replace the DSN without deleting the entry or its options. Copy the full Sentry-compatible DSN from the application's Data ingestion page, rather than a log source token. Validation checks its syntax, not whether Better Stack accepts it.
- **No events:** check the three filters, the event's logger/source, outbound HTTPS/DNS access to your ingesting host, and the Better Stack application. Handled exceptions are excluded by default. The SDK sends asynchronously; a successful integration setup does not prove delivery.
- **Another Sentry client is active:** disable Home Assistant's built-in Sentry integration or the other SDK owner before enabling Better Stack. The SDK's automatic logging and aiohttp hooks use a process-wide client; concurrent global clients are unsupported.
- **Changed Python files:** restart Home Assistant after installation or an update. Changing options only takes effect immediately.
- **Integration missing:** check the download path is `custom_components/betterstack/manifest.json`, restart after a manual install, and refresh the browser.

Report problems at [GitHub Issues](https://github.com/haveyourphil/homeassistant-betterstack/issues), with your Home Assistant and integration versions and a redacted error description. Do not include DSNs or unredacted logs.

To stop reporting, disable or delete **Better Stack** in Devices & services. Deleting that entry removes its DSN/options. To remove the code, also remove the download in Marketplace/HACS (or the manually installed folder) and restart.

## Development and releases

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest --cov=custom_components.betterstack --cov-report=term-missing
```

GitHub Actions runs tests, Ruff, hassfest, and the HACS validator used by Marketplace. Tests use Home Assistant 2026.10.4, cover SDK 2.48.0 and the latest compatible 2.x release, and block external network access.

The next proposed release is **0.2.0**, matching `manifest.json`. After validation passes, publish a GitHub Release tagged **`0.2.0`**; a tag by itself is insufficient. Repository archives supply the integration files, so no ZIP asset or build step is needed. For future releases, update the manifest version and publish the same tag. Keep `hacs.json`'s minimum Home Assistant version accurate. See [Marketplace releases](https://contributors.home-assistant.io/marketplace/guides/releases/) and the [audit and publishing checklist](docs/marketplace-audit.md).

Code is licensed under [Apache-2.0](LICENSE); see [NOTICE](NOTICE) for upstream and brand attribution. This is an independent community integration.

# Marketplace and Home Assistant audit

Reviewed on 27 October 2026 against Home Assistant 2026.10.4, current Home Assistant development sources, and the official publishing documentation. The built-in Marketplace starts with **2026.11**; this package also supports HACS on **2026.10**. The [Marketplace uses the same repository layout and `hacs.json` format](https://contributors.home-assistant.io/marketplace/how-it-works/).

## Existing installation and upgrade safety

**The manually installed code can be replaced by this Marketplace/HACS package while retaining the existing Better Stack config entry, DSN, unique ID, and options.** Install over `custom_components/betterstack`, then restart Home Assistant. Keep the entry in Devices & services.

The integration domain remains `betterstack`, the config flow remains version **1**, entry data remains `{"dsn": "..."}`, and the three existing option keys and defaults are unchanged. The manifest release version is separate from the config-entry schema version. No migration, replacement entry, entity migration, or persistent code-directory data is needed. Runtime state now belongs to typed `ConfigEntry.runtime_data`, which is not serialized into the entry.

Take a configuration backup first. A restart is required when replacing Python code, including the first takeover of the manual installation; an integration reload alone does not import updated files. The minimum supported HA version is now explicitly 2026.10.0. Concurrent global Sentry clients are unsupported: an enabled built-in Sentry entry or an already active SDK client prevents Better Stack setup rather than being silently replaced.

## Implementation decisions

| Area | Result and reason |
| --- | --- |
| Packaging | Minimal root `hacs.json` with the package name and minimum HA version. One domain folder contains every runtime asset. Standard release archives suffice; no ZIP build, `content_in_root`, or `persistent_directory`. |
| Manifest | Correct owner, documentation and issue URLs; `single_config_entry: true`; `service` retained. `cloud_polling` follows core Sentry's classification: this service makes outbound requests, with no incoming cloud push. Neither manifest classification changes runtime behavior. |
| SDK dependency | Keep the requirement, with `sentry-sdk>=2.48.0,<3.0.0`. Hassfest rejects an exact pin because HA's integration requirements also ship this package: an exact pin can conflict with later HA updates. The lower bound covers the APIs used; the upper bound excludes an untested major version. See [the official validator's shared-dependency checks](https://github.com/home-assistant/core/blob/dev/script/hassfest/requirements.py). Development tests pin the baseline separately. |
| Config flow | HA's manifest setting enforces single-instance, including concurrent flows and entries without the current unique ID. Remove the redundant manual entries check, retain the existing `betterstack` unique ID for new entries, and never rewrite an existing ID. |
| Form API | Use HA 2026.10's `probatio` schemas and a password selector for the DSN; persisted keys/types are unchanged. This matches [core Sentry's current form implementation](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/sentry/config_flow.py). |
| Options and DSN updates | All three filters read current `entry.options` for every event and apply immediately. No options update listener/reload is necessary. Reconfigure validates a replacement DSN and uses HA's update/reload helper, retaining the entry and options. |
| Lifecycle | Construct the exact owned SDK client on HA's import executor, then bind it globally on the event loop. Check for a conflicting client before and after initialization. Cancelled setup closes the newly constructed client. Unload and HA stop detach only this client and flush/close in an executor, with a two-second flush timeout. Cleanup is idempotent. |
| Callbacks | One hourly interval, one startup helper, and one stop listener, all cancelled on cleanup. The startup helper also handles setup after HA has already started. Refresh tasks belong to the config entry and are cancelled during unload. No growing list of hourly unsubscribe callbacks. |
| Event processing | Use event-loop metadata snapshots instead of iterating mutable HA component sets from logging threads. Keep release/channel metadata and the existing installation UUID. Recognize custom-component namespaces and tracebacks, core loggers, third-party packages, and both HA handled tags and SDK exception mechanisms. Own SDK/integration errors are excluded. Formatted log titles are retained. |
| SDK hooks | Retain logging and aiohttp exception capture. Disable automatic framework integrations, log ingestion, tracing propagation, sessions, and breadcrumbs. Remove SQLAlchemy instrumentation because this integration does not collect query breadcrumbs or performance traces; it adds unnecessary SQL hooks. SDK process-wide patches install once and become inactive without a bound client; they are not manually undone. |
| HA APIs | Retain current import-executor, installation-ID, system-info, custom-component loader and platform-context helpers. Core Sentry still uses these. Remove `SetupPhases`/`async_pause_setup`: those measure setup timing and are not needed for correctness. They were not identified as deprecated. |
| Return conventions | Successful setup/unload still return `True` for HA 2026.10 compatibility. Current guidance explicitly continues to support this for custom integrations. Failures raise `ConfigEntryError` with safe messages, never an SDK exception string containing a DSN. See [config-entry return values](https://contributors.home-assistant.io/core/integrations/config-entries/). |
| Translations | Complete English runtime translations, including Reconfigure and immediate-options guidance. Keep `strings.json` as an editable source; custom integrations use the finished `translations/en.json` at runtime. No unresolved placeholders are shipped in English. |
| Quality scale | Apply useful typing, flow tests, unloading, task ownership, privacy and troubleshooting principles without claiming a core quality tier. Entity/device registries, coordinators, availability, polling, discovery and entity migrations do not apply. |
| Setup and diagnostics | No network authentication probe or remote state is available during SDK setup, so avoid fictitious `ConfigEntryNotReady`, reauth, repairs, or a health/diagnostics status that implies delivery has been verified. Reconfigure supports correcting credentials. Safe errors and documentation cover actionable failures. |

## Privacy and public-repository review

`send_default_pii=False` is explicit. The integration no longer sends the OS username/timezone returned by HA's system-info helper, stack locals, SDK server name, inherited user email/IP details, request details, command-line arguments, or breadcrumbs. It recursively redacts its configured DSN and its keys, including in exception/log text and event keys, and removes credentials from HTTP(S) URLs. Trace headers are not added to unrelated outbound requests. The stable HA installation UUID is deliberately retained as a pseudonymous user ID/tag, not described as anonymous.

Error messages, source context, paths and arbitrary extras from other code can still contain unrelated personal data or secrets. These controls are not a guarantee that every possible log payload is anonymous. The README explains what is sent and tells users to redact issue reports.

Publication review covered all original tracked files, hidden repository configuration, the proposed publishable working tree, and **all five commits / eighteen distinct file blobs reachable from local refs**. Pattern checks and `detect-secrets` found no apparent real DSNs, tokens, credentials, API keys, private keys, or environment-specific runtime files. Historical DSN URLs contain placeholders. The scanner's one working-tree finding is an intentionally fake Basic Auth URL under `example.test` in the redaction test. Local virtual environments/caches are ignored; no runtime user data was moved into the integration folder. Git remotes contain no embedded credentials.

**Publication appears safe from a credential perspective.** Existing commit metadata exposes the author's name and a personal, non-GitHub-noreply email address. Those remain unchanged; review whether that personal metadata is acceptable. This review covers local reachable history, not an independent audit of every remote-only ref, GitHub issue, artifact or backup.

GitHub's API reported the repository **already public** during this audit. No visibility or remote settings were changed. It also reported Issues enabled, but no description, topics, or recognized license on the current remote branch. The new local Apache-2.0 license and NOTICE preserve the Home Assistant code's upstream license/attribution; GitHub must detect the license after these files are pushed. Brand assets have separate Simple Icons/Better Stack attribution.

## Validation

- Home Assistant's real test harness with network sockets blocked: **52 tests** on HA **2026.10.4**, with SDK **2.48.0** and **2.73.0**. Statement coverage is **100%**; a clean installation of `requirements-dev.txt` also passes. Coverage includes config flow, single-instance races/legacy IDs, invalid DSNs, options, Reconfigure, filtering/redaction, shutdown, setup cancellation, callback cleanup and repeated SDK unload/reload. A real SDK with an in-memory transport confirms no stacking of logging hooks and no writes to retired transports.
- Ruff lint/format and mypy over integration code pass.
- Official hassfest passes using both **2026.10.4** and current development sources (**d3a3874**). Container pulls were denied by the registry, so the upstream validator was run from source with its required dependencies.
- The current official HACS validators (**a15e87e**) for `hacsjson`, `integration_manifest`, `brands`, `information`, and `integration_categories` pass against a local file adapter. This is **not** a full GitHub-hosted action run. The optional `categories` field is omitted because HA 2026.10's hassfest rejects it; current HACS emits only a warning for its absence.
- The latest 2.x SDK emits a deprecation warning for `send_default_pii`. It remains explicitly false for compatibility with supported SDK 2.48.0 and the requested privacy setting. SDK 3.x is excluded.
- No live Better Stack request or running user Home Assistant configuration was changed or used for validation.

## Manual GitHub and Home Assistant steps

1. Commit and push the prepared changes. Set a GitHub repository description, for example **Home Assistant error reporting for Better Stack Errors**, and useful topics such as **betterstack** and **error-tracking**. Keep Issues enabled and confirm GitHub recognizes Apache-2.0 after pushing. Review the author metadata noted above. No visibility change appears necessary based on the API result.
2. Let **all** GitHub Actions jobs pass. The HACS action checks remote GitHub metadata/content and will fail while the description/topics/license are missing. No validator is ignored, and PR commenting is disabled. CI checks release tags against the manifest and tests the baseline plus latest compatible SDK.
3. Publish the first GitHub Release from the validated commit, tagged **`0.2.0`**, exactly matching `manifest.json`. No release/tag/history has been created by this work. Include the minimum HA version, retained entry/options, corrected filters/privacy behavior, global-client restriction, and automatic reload when reconfiguring the DSN in the release notes. Follow [official release guidance](https://contributors.home-assistant.io/marketplace/guides/releases/).
4. Back up HA, add this repository using the README's Marketplace/HACS link, download it over the manual files, and restart. Retain the existing Better Stack entry; confirm its options are unchanged. Marketplace itself requires HA 2026.11; HACS handles HA 2026.10.
5. Send a non-sensitive smoke-test event from Developer Tools > Actions, then confirm it appears in the intended Better Stack application:

   ```yaml
   action: system_log.write
   data:
     level: error
     message: "Better Stack installation test"
   ```

6. Optionally request default-catalog inclusion in `hacs/default` after a full release and clean CI. Custom-repository installation does not require catalog acceptance. See [catalog requirements](https://contributors.home-assistant.io/marketplace/guides/catalog/) and [the two recommended validation actions](https://contributors.home-assistant.io/marketplace/reference/validation/).

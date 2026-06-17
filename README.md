# Home Assistant Better Stack

Custom Home Assistant integration that sends error events to Better Stack Errors.

Better Stack Errors accepts Sentry-compatible SDK events, so this integration uses the Python Sentry SDK with the Better Stack DSN from your application's **Data ingestion** page. It sends Home Assistant error events and useful Home Assistant context only; it does not enable performance tracing or Better Stack log ingestion.

## Install

1. Copy `custom_components/betterstack` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration**.
4. Search for **Better Stack**.
5. Paste the Sentry-compatible Better Stack DSN:

   ```text
   https://$APPLICATION_TOKEN@$INGESTING_HOST/$APPLICATION_ID
   ```

## Options

- Whether handled errors should be sent.
- Whether errors from custom integrations should be sent.
- Whether errors from third-party Python packages should be sent.

Options are applied after reloading the integration or restarting Home Assistant.

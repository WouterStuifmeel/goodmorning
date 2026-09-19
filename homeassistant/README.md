# Home Assistant wiring (weather, so far)

This folder holds reference HA config, not app config - copy the relevant
bits into your own `configuration.yaml` / automations and adjust entity IDs.

1. `rest_commands.yaml` - one `rest_command` that POSTs a JSON payload to
   this service's `POST /episodes`. Point the URL at your Synology NAS's
   LAN IP (or a local DNS name) and the published port - HA runs in a VM
   on the NAS, not as a Docker container, so it can't reach this service
   by Docker service name; only plain LAN reachability applies.
2. `example_automation.yaml` - a time-triggered automation that calls
   `weather.get_forecasts`, aggregates today's forecast, maps it onto the
   service's `WeatherForecast` schema (`app/models/facts.py`), and fires the
   rest_command with a full `source_facts` payload.

## Why `weather.get_forecasts` instead of the entity state

A `weather.*` entity's *state* is just the current condition - it doesn't
carry today's high/low. `weather.get_forecasts` returns a forecast list
that does, but **not every integration supports the same forecast type**:

- `weather.forecast_thuis` (Buienradar) supports `type: daily` - one entry
  per day, already has `temperature`/`templow` as the day's high/low.
- `weather.openweathermap` only supports `type: hourly` - 3-hour steps, no
  single "today" entry at all. The example now aggregates every step whose
  *local* date matches today: min/max `temperature` across those steps for
  low/high, the day's peak `precipitation_probability`, and the step
  nearest midday (11:00-13:00 local) as the representative
  condition/wind - a 3am reading of "clear" shouldn't be narrated as
  today's weather.

If you switch weather integrations again, check what `type` values it
supports first (Developer Tools -> Actions -> `weather.get_forecasts`,
try `daily` then `hourly`) - a daily-native integration doesn't need the
aggregation logic at all, just `today_forecast = forecast[0]` like the
original version of this example did.

## Known gaps to fill in before this is real

- **Wind units**: `wind_speed` comes back in whatever unit your HA instance
  is configured for. `WeatherForecast.wind_kph` assumes km/h - convert in
  the template (or in HA's unit settings) if yours reports mph.
- **Some integrations don't provide every field**: `weather.forecast_thuis`
  (Buienradar-based) has no `precipitation_probability` - only a
  `precipitation` amount in mm. The template guards missing/undefined
  fields with `| default(..., true)` so the payload still renders (as
  `null`, which `WeatherForecast.precipitation_chance` allows) instead of
  crashing with `TypeError: Type is not JSON serializable: LoggingUndefined`.
  Check your integration's actual forecast keys via Developer Tools ->
  Template: `{{ state_attr('weather.<your_entity>', 'forecast') }}`.
- **`summary`**: there's no free-text summary from HA, so the example
  builds a crude one from condition + high. Worth handing this instead to
  the script provider to phrase naturally from `conditions`/`high_c`/`low_c`
  - may be simpler to just make `summary` optional and drop it from what
  HA supplies.
- **Calendar events and reminders**: not included yet - same automation
  should grow more `variables:` blocks (e.g. from `calendar.get_events`)
  that get folded into the same `source_facts` payload, so the whole thing
  stays one atomic POST rather than three partial ones.
- **Auth**: this hits the service with no credentials (see CLAUDE.md's
  "No auth on the API" remaining-work item) - fine on an internal Docker
  network, not fine once it's reachable over the LAN from a separate VM
  like this. Worth doing before relying on this setup day to day.
- **NAS IP stability**: use a DHCP reservation for the NAS (or local DNS)
  so the URL in `rest_commands.yaml` doesn't silently break.
- **Synology firewall**: Control Panel -> Security -> Firewall may block
  inbound port 8000 by default - add an allow rule for the HA VM's
  IP/subnet if the rest_command times out.

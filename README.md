# Crestron Home integration for Home Assistant

This repository hosts a custom [Home Assistant](https://www.home-assistant.io/) integration named **Crestron Home**.
Milestone 0 provides a scaffold that advertises the integration in Home Assistant's
**Add Integration** dialog but intentionally stops short of connecting to a
Crestron Home system.

## Installation

1. Copy `custom_components/crestron_home` to the `custom_components`
   directory inside your Home Assistant configuration.
2. Restart Home Assistant.
3. Open **Settings → Devices & Services → Add Integration** and search for
   "Crestron Home".

At this stage the configuration flow aborts with a friendly message while the
integration is under active development.

## Development

Run [`hassfest`](https://developers.home-assistant.io/docs/hassfest/) before
submitting changes to validate the integration metadata:

```bash
pipx run hassfest --action validate --integration-path custom_components/crestron_home
```

Future milestones will add authentication, communication with the Crestron Home
system, and entity platforms for controlling devices such as covers.

# Crestron Home integration for Home Assistant

Milestone 0 (M0) provides a scaffold for the future Crestron Home custom integration. The
integration can be discovered from **Settings → Devices & Services → Add Integration**, where a
placeholder config flow aborts with a friendly message that setup is not yet implemented.

## Development setup

1. Clone [home-assistant/core](https://github.com/home-assistant/core) next to this repository:
   ```bash
   git clone --depth=1 https://github.com/home-assistant/core hass-core
   ```
2. Run hassfest validation against the integration scaffold:
   ```bash
   (cd hass-core && python3 -m script.hassfest --action validate --integration-path ../custom_components/crestron_home)
   ```

## Roadmap

- **Milestone 1:** Implement API client, authentication, and initial cover platform support.
- **Milestone 2+:** Expand device coverage, add tests, and integrate discovery/onboarding flows.

## License

This project is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for details.

# Crestron Home integration for Home Assistant

Milestone 1 (M1) introduces authenticated communication with the Crestron Home REST API and a
connectivity check that confirms the number of rooms reported by the controller before finishing
setup.

## Configuration

1. On the Crestron controller, navigate to **Settings → System Control Options → Web API Settings**
   and create a long-lived Web API token.
2. In Home Assistant, go to **Settings → Devices & Services → Add Integration** and search for
   **Crestron Home**.
3. Enter the controller host, paste the Web API token, and choose whether to verify the SSL
   certificate. Disable SSL verification only when the controller uses a self-signed certificate.
4. Submit to test the connection. The flow logs in, retrieves the list of rooms, and displays how
   many were found before you confirm the configuration.

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

- **Milestone 1:** Implement API client, authentication, and REST connectivity validation.
- **Milestone 2+:** Expand device coverage, add tests, and integrate discovery/onboarding flows.

## License

This project is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for details.

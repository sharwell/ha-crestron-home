# Crestron Home integration for Home Assistant

Milestone 1 (M1) introduces authenticated communication with the Crestron Home REST API and a
connectivity check that confirms the number of rooms reported by the controller before finishing
setup. Milestone 2 (M2) extends the integration with read-only shade telemetry exposed as Home
Assistant cover entities.

## Configuration

1. On the Crestron controller, navigate to **Settings → System Control Options → Web API Settings**
   and create a long-lived Web API token.
2. In Home Assistant, go to **Settings → Devices & Services → Add Integration** and search for
   **Crestron Home**.
3. Enter the controller host, paste the Web API token, and choose whether to verify the SSL
   certificate. Disable SSL verification only when the controller uses a self-signed certificate.
4. Submit to test the connection. The flow logs in, retrieves the list of rooms, and displays how
   many were found before you confirm the configuration.

### Shades (Milestone 2)

- Every Crestron shade is exposed as a Home Assistant `cover` entity with the shade name reported
  by the controller. Entities surface the most recent shade position and availability status.
- The coordinator polls shade data every ~12 seconds while idle. Future control commands can call
  the coordinator's `boost()` helper to switch to 1.5 second polling for short bursts.
- The **Invert shade position** option is available under the integration's **Options** menu. When
  enabled, 0% represents fully open (Crestron polarity) instead of fully closed (Home Assistant
  polarity).
- Availability is derived from the controller's `connectionStatus` value. Offline shades appear as
  unavailable in Home Assistant until the controller reports them as connected again.

### Shade control (Milestone 3)

- Shade entities now implement Home Assistant's `open_cover`, `close_cover`, and
  `set_cover_position` services. Requests apply the global invert option and scale between
  Home Assistant's 0–100% representation and Crestron's 0–65535 range.
- Commands enqueue into a per-controller batcher. Calls landing within an 80 ms window coalesce
  into one `POST /cws/api/shades/SetState` request (up to 16 shades per batch) so grouped scenes
  lift together. Duplicate writes for the same shade keep the latest position before the batch is
  sent.
- After any successful write (full or partial), the coordinator bumps into fast polling (≈10 s at
  1–2 s intervals) so Home Assistant state converges quickly with the controller's telemetry.
- To verify batching manually, enable debug logging (see `sample_config/configuration.yaml` in the
  repo) and trigger a scene that adjusts eight shades at once. A single DEBUG line similar to
  `POST /shades/SetState items=8 ids=[...] status=success` confirms one request served the entire
  batch.

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
- **Milestone 2:** Surface read-only shade telemetry via cover entities, including availability and
  global polarity inversion.
- **Milestone 3:** Write control for shades (open/close/set position) with request batching.
- **Milestone 4:** Micro-calibration curves to improve visual position uniformity.
- **Milestone 5:** Stop operation refinements for hold/release behavior.
- **Milestone 6:** Discovery and UX polish after milestone-wide deliverables.
- **Milestone 7:** Broader tests, documentation, and practical examples.

## License

This project is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for details.

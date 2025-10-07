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
  polarity). This setting now acts as the global default for the calibration editor introduced in
  Milestone 4.
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

### Calibration (Milestone 4)

- Each shade can expose a micro-calibration curve so intermediate positions align visually across
  different shade models. Curves are edited from **Options → Calibrate a shade** and consist of at
  least two anchors describing how a Home Assistant percentage maps to the controller's 0–65535 raw
  value.
- Anchors must remain in ascending percent order, start at 0%, and end at 100%. Raw values must
  never decrease between anchors—flat segments are allowed when a range of raw values should report
  the same Home Assistant percentage. The options flow validates these rules before saving.
- The editor supports inserting anchors between any two existing points, removing interior anchors,
  and resetting back to the default `(0%, 0)` and `(100%, 65535)` endpoints. A per-shade **Invert
  axis** toggle overrides the global polarity when a single window is mounted opposite the rest.
- Shade entities automatically apply the configured curve when reporting state and when accepting
  service calls. For example, two calibrated shades that receive `set_cover_position: 23` will send
  different raw targets while reaching a visually matching opening.

### Visual groups (Milestone 7)

- Shades can be arranged into **Visual groups** from **Options → Visual groups**. Groups provide a
  lightweight way to describe which windows should finish together when predictive stops or grouped
  scenes run.
- With no explicit groups configured the integration maintains the existing behavior: all shades are
  treated as a single cohort for alignment and batching decisions.
- After you create one or more groups, only shades assigned to the same group align with one
  another. Unassigned shades behave independently so accidental cross-room coupling is avoided.
- Diagnostics list the configured groups, per-shade membership, and recent plan/flush events tagged
  with the group identifier for easier troubleshooting.

### Hold-to-move stop (Milestone 5A)

- Shade entities now advertise the `stop_cover` service. Because the REST API does not expose a
  native STOP command, the integration performs a best-effort freeze: it reads each shade's most
  recent reported position and posts that value straight back to
  `POST /cws/api/shades/SetState`. The same batcher used for open/close/set commands collects STOP
  requests for up to 80 ms so scenes or simultaneous button releases flush as one payload. The
  coordinator immediately bumps into fast polling so Home Assistant reflects the halted position as
  soon as the controller reports it.
- If a shade's current position is unavailable at release time the STOP request skips that shade
  (others still post). Calibrations and per-shade polarity continue to apply when the integration
  needs to map a Home Assistant percentage back to the controller's raw 0–65535 range.
- A Matter wall switch blueprint at
  `blueprints/automation/crestron_home/matter_shade_hold_release.yaml` demonstrates hold/release
  wiring. Choose the Matter devices that expose the open/close buttons and pick the corresponding
  hold and release device triggers surfaced by the Matter driver. Holding calls `cover.open_cover`
  or `cover.close_cover`; releasing either button calls `cover.stop_cover` so shades coast to a
  stop.

### Predictive Stop with online learning (Milestone 6)

- Predictive Stop replaces the best-effort freeze with an estimator that predicts where a shade will
  land once transport latency and deceleration are accounted for. When you press STOP, the planner
  projects each moving shade forward, clamps to avoid any backtracking, and submits a batched
  `SetState` call so grouped shades within the same visual group finish together without coupling
  to other groups.
- Every shade maintains a tiny model of steady-state speed and command latency. The learning system
  blends recursive least squares (speed vs. position) with an exponential moving average of the
  command response time. Samples are collected from the coordinator's burst polls immediately after
  any write.
- Predictive Stop is enabled by default and can be toggled from **Options → Predictive Stop**. When
  disabled the integration reverts to the Milestone 5A freeze-at-last-poll behavior.
- Per-shade learned parameters can be cleared from **Options → Reset learned parameters**. This also
  resets the in-memory estimator so subsequent traversals rebuild a fresh model.
- Diagnostics now expose the current learning parameters, visual group configuration, and the last
  few stop outcomes. Navigate to the integration tile → **... → Diagnostics** to download a JSON
  snapshot that includes per-shade steady-state speeds, response latency estimates, recent stop
  telemetry, and the grouped plan/flush history recorded by the coordinator.

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

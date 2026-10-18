# Indus3D roadmap

This is a direction-of-travel document, not a release promise. Work is prioritised by printer safety, evidence from real hardware, and usefulness to Klipper users.

## Now

- Stabilise the dashboard, simulator, and Flask/Moonraker boundary
- Document validated versus experimental quality-control behaviour
- Improve printer-profile handling, empty states, and real-printer diagnostics
- Add focused frontend and backend regression coverage

## Next

- Guided calibration workflow for bed levelling, PID, flow, and input shaping
- Better post-print reports from the SQLite audit trail
- More test shapes and simulator fault scenarios
- Community-contributed printer profiles and compatibility reports
- Better camera-stream configuration and diagnostics

## Research and hardware validation

- Validate vibration-informed fault detection with ADXL-equipped toolheads
- Integrate camera/YOLO inspection only after hardware and dataset validation
- Measure whether variable input shaping and flow adjustments improve print quality on repeatable test prints

## Good first issues

Good first contributions should be scoped so that they can be tested in simulation. Useful examples include:

- Responsive and accessible dashboard improvements
- Clearer error/empty/loading states
- Unit tests for model calculations and API responses
- Additional simulator geometry and fixture data
- Documentation for supported Klipper/Moonraker setups
- Importable printer-profile examples with secrets removed

When proposing work, describe how it can be tested without risking a real printer.

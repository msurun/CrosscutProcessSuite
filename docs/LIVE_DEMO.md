# Live demos and UaExpert

Two scripted OPC UA clients run against the simulated mill circuit. Each starts its own server
on a free local port and prints the endpoint. Run everything from the repository root after
`pip install -r requirements-dev.txt`.

## Demo 1: loop health with a sticking valve

```
python opcua/examples/live_demo.py --scenario stiction
```

Options: `--hours 5`, `--band 12` (valve stiction band in %). The run takes about 3 minutes
(100 simulated seconds per wall-clock second).

1. The client steps the HPGR press setpoint by +1.0 at 0.5 h.
2. From 3 h on it prints the loop health once per simulated hour.
3. Expected pattern (seen on 2026-10-14): about 36 % at 3 h (warning, finding "oscillating",
   verdict inconclusive), about 21 % at 4 h (problem, findings "oscillating" and "stiction",
   verdict "stiction").

Limits, stated plainly:

- The band is 12 %. With full measurement noise the detector does not find bands below about
  8 % reliably (`experiments/exp01_stiction_validation/results`).
- Samples slower than about 15 s hide the fault. The demo samples every 10 s.
- A square-wave load disturbance is a known false alarm of the detector.

## Demo 2: retune a detuned loop

```
python opcua/examples/retune_demo.py
```

About 4 minutes. Three runs, then one comparison:

1. The detuned loop answers a setpoint step.
2. An open-loop step test of the same loop is recorded.
3. The tuning report derives SIMC gains from that step test. The loop runs again with them.

The last two lines show health and the integral of |SP - PV| before and after (seen on
2026-10-14: 48 % to 100 %, integral 1566 to 75). Tuning stays advisory: the gains go only to the
simulator, nothing is written to a DCS. The evidence over several seeds is in
`experiments/exp03_retune/results/retune_validation.md`.

## Connect UaExpert (owner check, not done yet)

While a demo runs:

1. Add a server in UaExpert with the printed `opc.tcp://127.0.0.1:<port>` address.
2. Security policy None, anonymous login.
3. Browse Objects > Plant. Variables are named `sim.mc.hpgr_press`, `sim.mc.hpgr_press_sp`,
   `sim.mc.hpgr_press_out` and `sim.mc.hpgr_press_mode` (0 MAN, 1 AUTO, 2 CAS), in the namespace
   `urn:crosscut:sim`. Read the namespace index from the address space; it may differ.
4. Drag PV, SP and OUT into the Data Access View or the Trend View. Writing the SP node moves
   the setpoint.
5. `sim.heartbeat` is the only support variable a client may write. The fault itself (the
   stiction band) is deliberately not exposed.

The port changes with every run. For a fixed port start the server alone (default 4840):

```
python -m crosscut_opcua.server --plant mill_circuit --scenario stiction --speed 60
```

After the check, add a line to `docs/IMPLEMENTATION_LOG.md`: UaExpert version and what happened.

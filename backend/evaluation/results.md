# VISTARA-X evaluation results

Generated 2026-10-21T07:40:56+00:00 by `python -m app.evaluation` on Windows 10, AMD64 Family 23 Model 24 Stepping 1, AuthenticAMD (327.4 s). headless engine, simulated sensors, fixed seeds; obstacle ground truth used only for the metrics.

## Predictive avoidance vs reactive baseline

Scenario `crossing`, 9 runs per mode: crossing person at 0.6, 0.9, 1.2 m/s, starting 0, 4, 8 s early.

| Metric | Predictive | Reactive baseline |
|---|---|---|
| Goal completion | 9/9 | 7/9 |
| Collisions (total) | 0 | 2 |
| Near misses (< 0.25 m, total) | 0 | 3 |
| Closest approach to a moving obstacle, worst run (m) | 0.329 | -0.033 |
| Closest approach, mean over runs (m) | 1.329 | 1.007 |
| Task duration, mean (s) | 26.23 | 24.94 |
| Path length, mean (m) | 17.54 | 17.43 |
| Replans per run, mean | 3.11 | 2.56 |
| 1 s prediction error, mean (m) | 0.202 | 0.202 |
| Simulation step time, mean / max (ms) | 30.67 / 753.47 | 31.73 / 1092.72 |

### Individual runs

| Mode | Person speed (m/s) | Start offset (s) | Result | Time (s) | Path (m) | Replans | Collisions | Near misses | Closest approach (m) |
|---|---|---|---|---|---|---|---|---|---|
| predictive | 0.6 | 0 | goal_reached | 28.95 | 17.62 | 5 | 0 | 0 | 1.255 |
| predictive | 0.6 | 4 | goal_reached | 26.3 | 17.78 | 4 | 0 | 0 | 2.13 |
| predictive | 0.6 | 8 | goal_reached | 23.45 | 17.15 | 1 | 0 | 0 | 1.846 |
| predictive | 0.9 | 0 | goal_reached | 28.5 | 17.72 | 3 | 0 | 0 | 0.904 |
| predictive | 0.9 | 4 | goal_reached | 26.0 | 17.24 | 3 | 0 | 0 | 1.254 |
| predictive | 0.9 | 8 | goal_reached | 25.5 | 17.65 | 3 | 0 | 0 | 0.82 |
| predictive | 1.2 | 0 | goal_reached | 27.6 | 17.55 | 2 | 0 | 0 | 0.329 |
| predictive | 1.2 | 4 | goal_reached | 26.55 | 17.73 | 4 | 0 | 0 | 1.487 |
| predictive | 1.2 | 8 | goal_reached | 23.2 | 17.43 | 3 | 0 | 0 | 1.939 |
| reactive | 0.6 | 0 | goal_reached | 27.85 | 17.64 | 5 | 0 | 0 | 0.55 |
| reactive | 0.6 | 4 | goal_reached | 26.3 | 17.78 | 4 | 0 | 0 | 2.13 |
| reactive | 0.6 | 8 | goal_reached | 23.45 | 17.15 | 1 | 0 | 0 | 1.846 |
| reactive | 0.9 | 0 | stopped | 20.75 | 16.63 | 2 | 1 | 1 | -0.014 |
| reactive | 0.9 | 4 | goal_reached | 25.95 | 17.24 | 3 | 0 | 0 | 1.254 |
| reactive | 0.9 | 8 | stopped | 10.6 | 8.72 | 1 | 1 | 1 | -0.033 |
| reactive | 1.2 | 0 | goal_reached | 20.8 | 17.15 | 0 | 0 | 1 | 0.203 |
| reactive | 1.2 | 4 | goal_reached | 27.05 | 17.61 | 4 | 0 | 0 | 1.188 |
| reactive | 1.2 | 8 | goal_reached | 23.2 | 17.43 | 3 | 0 | 0 | 1.939 |

## Scenario checks

| Check | Result | Detail |
|---|---|---|
| Static obstacle on the direct route (crate-1) | pass | goal goal_reached, path 17.62 m (straight line 17.0 m), collisions 0 |
| Moving obstacle crossing the route (person-1, does not give way) | pass | 5 predictive decisions, min clearance to moving obstacles 1.255 m, near misses 0 |
| Moving obstacle that changes direction (cart-1, rectangular loop) | pass | 1 s prediction error mean 0.19 m, max 1.177 m (the max occurs at turns, where constant velocity is wrong) |
| Uncertain / lost track (person walks behind the walls) | pass | 1 track(s) lost and dropped; coasting tracks are shown as uncertain and limit speed near the route |
| Route blocked after navigation begins | pass | 1 replan(s), goal goal_reached, collisions 0 |
| Hinglish command: 'Robot ko exit tak le jao' (text-only, confirmed, no audio) | pass | language hi-Latn, destination Exit, goal goal_reached in 28.95 s |
| Unreachable destination (inner bay, sealed) | pass | not started automatically even in trusted mode; after confirmation status blocked, travelled 0.0 m |

These numbers come from one simulated environment with simple motion models. They are not a measure of real-world safety.

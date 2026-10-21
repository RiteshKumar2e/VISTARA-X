Saved occupancy maps in ROS map_server format (`<name>.pgm` + `<name>.yaml`).

`warehouse_demo` is the documented demo map. It was produced by the backend's own
exploration in the *Warehouse aisle* scenario (simulated LiDAR + wheel odometry,
scan-matching SLAM, 0.1 m per cell, origin (0, 0), 89.75% of the area known, pose error
8.5 cm at the end of the run, 0 collisions). It is a simulation-generated map, not a
map of a real building. The patrolling person was standing at (17, 2) while the map
was made, so that spot appears as a small obstacle.

Load it from the dashboard (Mapping > Save, load, export and import > Load) or with
`POST /mapping/load {"name": "warehouse_demo"}`, then choose *Imported / saved map* as
the planner map. Other maps saved here are git-ignored.

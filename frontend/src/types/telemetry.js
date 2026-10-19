// JSDoc description of the telemetry contract (version 1) shared by the backend
// (backend/app/simulation/engine.py: SimulationEngine.snapshot) and this frontend.
// Bump TELEMETRY_VERSION on both sides when making a breaking change.

export const TELEMETRY_VERSION = 1;

/**
 * @typedef {'idle'|'planning'|'navigating'|'paused'|'goal_reached'|'blocked'|'stopped'} MissionStatus
 *
 * @typedef {Object} Detection
 * @property {string} label
 * @property {number|null} confidence   null for the ground-truth simulated detector
 * @property {[number, number, number, number]} bbox  x1, y1, x2, y2 in camera pixels
 * @property {number|null} distance     metres, from the camera depth buffer
 * @property {number} bearing_deg       positive = left of the optical axis
 * @property {'yolov8'|'ground_truth'} source
 *
 * @typedef {Object} Track
 * @property {number} id
 * @property {string} label
 * @property {number} x
 * @property {number} y
 * @property {boolean} confirmed
 * @property {boolean} stale
 *
 * @typedef {Object} Telemetry
 * @property {'telemetry'} type
 * @property {number} version
 * @property {number} seq               strictly increasing; older messages are dropped
 * @property {number} sim_time          seconds of simulated time
 * @property {string} scenario
 * @property {{id:number,status:MissionStatus,waiting:boolean,reason:string,elapsed:number,
 *   distance_travelled:number,replans:number,safety_stops:number,goal_reached:boolean,
 *   progress:number|null}} mission
 * @property {{x:number,y:number,theta:number,heading_deg:number,v:number,w:number,radius:number}} robot
 * @property {{x:number,y:number}|null} target
 * @property {number|null} distance_to_target
 * @property {[number, number][]} path
 * @property {{index:number,x:number,y:number}|null} current_waypoint
 * @property {Object|null} last_plan
 * @property {{clearance:number,nearest:string,warning:boolean,collisions:number,in_contact:boolean,
 *   inflation:number,physics:'pybullet'|'analytic'}} safety
 * @property {Object[]} obstacles
 * @property {{max_speed:number,safety_margin:number,moving_obstacles:boolean}} params
 * @property {Object[]} events
 * @property {{mode:string,source_label:string,enabled:boolean,rate_hz:number,confidence_threshold:number,
 *   renderer:'pybullet'|'raycast',stale:boolean,detections:Detection[],tracks:Track[],scene:Object}} perception
 */

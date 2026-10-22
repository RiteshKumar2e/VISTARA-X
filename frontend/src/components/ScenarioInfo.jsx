import { CheckIcon, InfoIcon } from './Icons';

// Where each scenario's situation occurs in the real world, and what the prototype shows
// for it. Statements are general; no deployment of VISTARA-X is claimed.
const INFO = {
  warehouse: {
    setting: 'Warehouse and factory logistics',
    real: 'Autonomous mobile robots already carry goods between racks, packing stations and docks in many warehouses and factories.',
    benefits: [
      'Moves goods without tracks or floor tape: A* plans a route on the map',
      'Slows and replans around people and pallets instead of stopping the whole line',
      'Says honestly when an aisle is completely blocked',
    ],
    tryIt: 'Say or type "Take the robot to the loading bay", then drop an obstacle on the route.',
  },
  crossing: {
    setting: 'Shared corridors with people',
    real: 'Robots that share space with people must expect walkers who do not give way, for example in busy factories, airports and malls.',
    benefits: [
      'Predicts where a person will be 0.5-3 s ahead and slows before the paths meet',
      'Steps aside when someone walks straight at it',
      'Measured here: 0 collisions in 9 runs vs 2 for a purely reactive robot (simulation)',
    ],
    tryIt: 'Click "Run predictive demo" in the Guided demo card.',
  },
  hospital: {
    setting: 'Hospital delivery',
    real: 'Some hospitals use delivery robots to carry medicines, linen, meals and lab samples between departments, so nurses spend more time with patients.',
    benefits: [
      'Staff name the destination by voice or text in English or Hindi: "Pharmacy", "ICU", "Ward A"',
      'Gives way in corridors and steps aside for visitors who keep walking',
      'Text-first controls and visual alerts for people who cannot hear an alarm',
      'Emergency stop that never depends on speech recognition',
    ],
    tryIt: 'Type "Robot ko pharmacy tak le jao" or "Take the robot to the ICU", then confirm.',
  },
  campus: {
    setting: 'Campus delivery',
    real: 'Small sidewalk delivery robots operate on some university campuses, carrying food and parcels between buildings.',
    benefits: [
      'Plans around buildings, trees, benches and the fountain',
      'Tracks students walking across the plaza and predicts their path',
      'Hindi and English commands: "Robot ko library tak le jao", "Take the robot to the hostel"',
    ],
    tryIt: 'Type "Take the robot to the hostel" and watch it cross the plaza.',
  },
  slalom: {
    setting: 'Test track',
    real: 'A course for checking route planning through narrow, winding gaps.',
    benefits: ['Long detours are found and checked before the robot moves'],
    tryIt: 'Select the far corner as the destination and start the mission.',
  },
  enclosed: {
    setting: 'Unreachable destination',
    real: 'Real robots meet locked doors and blocked rooms; a safe robot must say so instead of forcing its way.',
    benefits: ['Reports Blocked and does not move when no safe route exists'],
    tryIt: 'Type "Go to the inner bay": the robot explains that no route exists.',
  },
};

/** Real-world context for the loaded scenario. */
export function ScenarioInfo({ scenario }) {
  const info = INFO[scenario];
  if (!info) return null;
  return (
    <aside className="scenario-info" aria-label="Real-world use of this scenario">
      <p className="scenario-info-head">
        <InfoIcon size={14} /> <strong>Real-world use: {info.setting}</strong>
      </p>
      <p className="small">{info.real}</p>
      <ul className="scenario-benefits">
        {info.benefits.map((b) => (
          <li key={b}>
            <CheckIcon size={13} /> {b}
          </li>
        ))}
      </ul>
      <p className="small">
        <strong>Try it:</strong> {info.tryIt}
      </p>
      <p className="muted small">
        Intended use only. This is a simulation; VISTARA-X has not been deployed or validated in a real {info.setting.toLowerCase()} setting.
      </p>
    </aside>
  );
}

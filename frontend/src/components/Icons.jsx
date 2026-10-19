// Small hand-drawn inline SVG icons (24 x 24 grid, 1.75 stroke). Decorative by
// default: every icon is aria-hidden and must sit next to a visible text label.

function Svg({ size = 16, className, children, fill = 'none' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill}
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ? `icon ${className}` : 'icon'}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const PlayIcon = (p) => (
  <Svg {...p}>
    <path d="M7 5v14l12-7z" fill="currentColor" />
  </Svg>
);
export const PauseIcon = (p) => (
  <Svg {...p}>
    <path d="M8 5v14M16 5v14" strokeWidth="3" />
  </Svg>
);
export const StopIcon = (p) => (
  <Svg {...p}>
    <rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" />
  </Svg>
);
export const ResetIcon = (p) => (
  <Svg {...p}>
    <path d="M4 12a8 8 0 1 0 2.4-5.7" />
    <path d="M4 4v4h4" />
  </Svg>
);
export const CrosshairIcon = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="6" />
    <path d="M12 2v5M12 17v5M2 12h5M17 12h5" />
  </Svg>
);
export const ObstacleIcon = (p) => (
  <Svg {...p}>
    <rect x="5" y="5" width="14" height="14" rx="1" />
    <path d="M5 12h14M12 5v14" />
  </Svg>
);
export const ClearIcon = (p) => (
  <Svg {...p}>
    <path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" />
  </Svg>
);
export const MenuIcon = (p) => (
  <Svg {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Svg>
);
export const CloseIcon = (p) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);
export const ChevronIcon = (p) => (
  <Svg {...p}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
);
export const SpinnerIcon = ({ className = '', ...p }) => (
  <Svg {...p} className={`spin ${className}`}>
    <path d="M12 3a9 9 0 1 0 9 9" />
  </Svg>
);
export const DisconnectedIcon = (p) => (
  <Svg {...p}>
    <path d="M4 12a8 8 0 0 1 13.7-5.6M20 12a8 8 0 0 1-13.7 5.6" />
    <path d="M3 3l18 18" />
  </Svg>
);
export const CameraIcon = (p) => (
  <Svg {...p}>
    <rect x="3" y="7" width="18" height="12" rx="2" />
    <circle cx="12" cy="13" r="3.5" />
    <path d="M9 7l1.5-2h3L15 7" />
  </Svg>
);

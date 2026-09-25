import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

const base = (size?: number) => ({
  width: size ?? 20,
  height: size ?? 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
});

export const SearchIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
);
export const PinIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M12 22s-7-7-7-12a7 7 0 1 1 14 0c0 5-7 12-7 12Z" /><circle cx="12" cy="10" r="2.5" /></svg>
);
export const HeartIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" /></svg>
);
export const HeartFilledIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} fill="currentColor" {...p}><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" /></svg>
);
export const StarIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M12 3.5 14.6 9l5.9.9-4.3 4.1 1 5.9L12 17l-5.2 2.9 1-5.9L3.5 9.9 9.4 9 12 3.5Z" /></svg>
);
export const StarFilledIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} fill="currentColor" {...p}><path d="M12 3.5 14.6 9l5.9.9-4.3 4.1 1 5.9L12 17l-5.2 2.9 1-5.9L3.5 9.9 9.4 9 12 3.5Z" /></svg>
);
export const FilterIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M4 6h16M7 12h10M10 18h4" /></svg>
);
export const CloseIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
export const ChevronDownIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="m6 9 6 6 6-6" /></svg>
);
export const ChevronLeftIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="m15 6-6 6 6 6" /></svg>
);
export const ChevronRightIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="m9 6 6 6-6 6" /></svg>
);
export const PlusIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M12 5v14M5 12h14" /></svg>
);
export const MinusIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M5 12h14" /></svg>
);
export const CompassIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" /></svg>
);
export const ListIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" /></svg>
);
export const MapIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20V6.5Z" /><path d="M9 4v13.5M15 6.5V20" /></svg>
);
export const HomeIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10" /></svg>
);
export const ExploreIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" /></svg>
);
export const SavedIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M5 4h14v17l-7-4-7 4V4Z" /></svg>
);
export const BellIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2H4.5L6 16Z" /><path d="M10 21a2 2 0 0 0 4 0" /></svg>
);
export const UserIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 5-6 8-6s6.5 2 8 6" /></svg>
);
export const BoltIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M13 3 5 14h6l-1 7 8-11h-6l1-7Z" /></svg>
);
export const ClockIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
);
export const CheckIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="m5 12 5 5 9-11" /></svg>
);
export const GlobeIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></svg>
);
export const NavIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M3 11h18l-3 9H6l-3-9Z" /><circle cx="7" cy="15.5" r="1.5" /><circle cx="17" cy="15.5" r="1.5" /><path d="M9 11 12 4l3 7" /></svg>
);
export const SortIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M4 7h16M6 12h12M9 17h6" /></svg>
);
export const AlertTriangleIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M12 4 2 21h20L12 4Z" /><path d="M12 10v5M12 18h.01" /></svg>
);
export const InboxIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><path d="M3 13h5l1 2h6l1-2h5" /><path d="M3 13V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v7" /></svg>
);
export const InfoIcon = ({ size, ...p }: IconProps) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8h.01M11 12h1v4" /></svg>
);

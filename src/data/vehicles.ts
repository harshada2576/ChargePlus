import type { ConnectorType } from "./types";

export type VehicleCategory = "4W_Passenger" | "2W_Scooter" | "3W_Commercial";

export interface VehicleProfile {
  id: string;
  brand: string;
  model: string;
  variant: string;
  category: VehicleCategory;
  usableBatteryKwh: number;
  maxDcPowerKw: number | null;
  maxAcPowerKw: number;
  compatibleConnectors: ConnectorType[];
  provenance: {
    source: string;
    verified: boolean;
  };
}

/**
 * Curated, versioned vehicle dataset for Indian EV market.
 * Missing/unverified parameters are explicitly null or marked unverified.
 */
export const CURATED_INDIAN_VEHICLES: VehicleProfile[] = [
  {
    id: "tata-nexon-ev-lr",
    brand: "Tata",
    model: "Nexon.ev",
    variant: "Long Range (Empowered+)",
    category: "4W_Passenger",
    usableBatteryKwh: 40.5,
    maxDcPowerKw: 50,
    maxAcPowerKw: 7.2,
    compatibleConnectors: ["CCS2", "Type 2"],
    provenance: {
      source: "Tata Motors Technical Spec Sheet 2024",
      verified: true,
    },
  },
  {
    id: "tata-tiago-ev-mr",
    brand: "Tata",
    model: "Tiago.ev",
    variant: "Medium Range",
    category: "4W_Passenger",
    usableBatteryKwh: 19.2,
    maxDcPowerKw: 25,
    maxAcPowerKw: 3.3,
    compatibleConnectors: ["CCS2", "Type 2"],
    provenance: {
      source: "Tata Motors Technical Spec Sheet 2024",
      verified: true,
    },
  },
  {
    id: "mg-zs-ev",
    brand: "MG",
    model: "ZS EV",
    variant: "Excite / Exclusive",
    category: "4W_Passenger",
    usableBatteryKwh: 50.3,
    maxDcPowerKw: 80,
    maxAcPowerKw: 7.4,
    compatibleConnectors: ["CCS2", "Type 2"],
    provenance: {
      source: "MG Motor India Official OEM Specifications",
      verified: true,
    },
  },
  {
    id: "mahindra-xuv400-el",
    brand: "Mahindra",
    model: "XUV400",
    variant: "EL Pro",
    category: "4W_Passenger",
    usableBatteryKwh: 39.4,
    maxDcPowerKw: 50,
    maxAcPowerKw: 7.2,
    compatibleConnectors: ["CCS2", "Type 2"],
    provenance: {
      source: "Mahindra Electric Mobility Spec 2024",
      verified: true,
    },
  },
  {
    id: "hyundai-ioniq-5",
    brand: "Hyundai",
    model: "Ioniq 5",
    variant: "RWD 72.6kWh",
    category: "4W_Passenger",
    usableBatteryKwh: 72.6,
    maxDcPowerKw: 220, // 800V architecture
    maxAcPowerKw: 11.0,
    compatibleConnectors: ["CCS2", "Type 2"],
    provenance: {
      source: "Hyundai Motor India Spec 2024",
      verified: true,
    },
  },
  {
    id: "ather-450x-gen3",
    brand: "Ather",
    model: "450X",
    variant: "Gen 3 (3.7kWh)",
    category: "2W_Scooter",
    usableBatteryKwh: 3.7,
    maxDcPowerKw: null, // AC slow charging or Ather Grid DC proprietary
    maxAcPowerKw: 3.3,
    compatibleConnectors: ["Bharat AC001", "Type 2"],
    provenance: {
      source: "Ather Energy Spec Sheet 2024",
      verified: true,
    },
  },
];

export interface CompatibilityResult {
  isCompatible: boolean;
  compatibleConnectors: ConnectorType[];
  incompatibleReason?: string;
}

/**
 * Evaluates connector compatibility against a vehicle profile.
 */
export function checkVehicleCompatibility(
  vehicle: VehicleProfile,
  stationConnectors: { type: ConnectorType; powerKw: number | null }[]
): CompatibilityResult {
  const matches = stationConnectors.filter((c) =>
    vehicle.compatibleConnectors.includes(c.type)
  );

  if (matches.length > 0) {
    return {
      isCompatible: true,
      compatibleConnectors: Array.from(new Set(matches.map((m) => m.type))),
    };
  }

  return {
    isCompatible: false,
    compatibleConnectors: [],
    incompatibleReason: `Station lacks compatible plugs (${vehicle.compatibleConnectors.join(", ")})`,
  };
}

export interface ChargingEstimate {
  energyNeededKwh: number;
  effectivePowerKw: number;
  estimatedHours: number;
  estimatedMinutes: number;
  limitingFactor: "vehicle" | "charger" | "unknown";
  disclaimer: string;
}

/**
 * Simplified energy-based charging time estimate.
 * Formula: Time ≈ Energy Required (kWh) / Effective Power (kW) * Efficiency (0.90)
 * Note: Actual charging varies by battery thermal conditions, BMS tapering curves, and voltage.
 */
export function estimateChargingTime(params: {
  vehicle: VehicleProfile;
  chargerType: ConnectorType;
  chargerPowerKw: number | null;
  startSocPct?: number;
  targetSocPct?: number;
}): ChargingEstimate | null {
  const {
    vehicle,
    chargerType,
    chargerPowerKw,
    startSocPct = 20,
    targetSocPct = 80,
  } = params;

  if (chargerPowerKw === null || chargerPowerKw <= 0) {
    return null;
  }

  const isDc = chargerType.startsWith("CCS") || chargerType === "CHAdeMO";
  const vehicleMaxPower = isDc ? vehicle.maxDcPowerKw : vehicle.maxAcPowerKw;

  let effectivePower = chargerPowerKw;
  let limitingFactor: "vehicle" | "charger" | "unknown" = "charger";

  if (vehicleMaxPower !== null) {
    if (vehicleMaxPower < chargerPowerKw) {
      effectivePower = vehicleMaxPower;
      limitingFactor = "vehicle";
    } else {
      effectivePower = chargerPowerKw;
      limitingFactor = "charger";
    }
  }

  const socDelta = Math.max(0, targetSocPct - startSocPct) / 100;
  const energyNeededKwh = vehicle.usableBatteryKwh * socDelta;

  // Account for typical AC/DC charging efficiency losses (~90% efficiency)
  const effectiveThroughputKw = effectivePower * 0.9;
  const totalHours = energyNeededKwh / effectiveThroughputKw;
  const totalMinutes = Math.round(totalHours * 60);

  return {
    energyNeededKwh: Number(energyNeededKwh.toFixed(1)),
    effectivePowerKw: Number(effectivePower.toFixed(1)),
    estimatedHours: Math.floor(totalMinutes / 60),
    estimatedMinutes: totalMinutes % 60,
    limitingFactor,
    disclaimer:
      "Estimate based on linear energy throughput with 90% power efficiency. Real-world session time depends on BMS charge curve tapering (especially >80% SoC), ambient temperature, and station supply grid load.",
  };
}

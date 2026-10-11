"use client";

import { useState } from "react";
import { BottomSheet } from "./BottomSheet";
import { Button } from "./Button";
import { useI18n } from "@/i18n/I18nProvider";
import type { ConnectorType, FiltersState } from "@/data/types";
import { cx } from "@/lib/util";

const ALL_CONNECTORS: ConnectorType[] = ["CCS2", "CCS1", "CHAdeMO", "Type 2", "Type 1", "Bharat AC001"];

const DISTANCE_OPTIONS = [0, 2, 5, 10, 20];
const POWER_OPTIONS = [0, 22, 50, 120];
const PRICE_OPTIONS = [0, 15, 18, 22];
const CHARGER_OPTIONS = [0, 2, 4, 8];

type Props = {
  open: boolean;
  onClose: () => void;
  value: FiltersState;
  onChange: (next: FiltersState) => void;
};

export function FiltersPanel({ open, onClose, value, onChange }: Props) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<FiltersState>(value);

  // sync draft when opening
  function syncOpen() {
    setDraft(value);
  }

  function toggleConnector(c: ConnectorType) {
    setDraft((d) => ({
      ...d,
      connectorTypes: d.connectorTypes.includes(c)
        ? d.connectorTypes.filter((x) => x !== c)
        : [...d.connectorTypes, c],
    }));
  }

  function reset() {
    setDraft({
      distanceKm: 0,
      connectorTypes: [],
      minPowerKw: 0,
      openNow: false,
      availableOnly: false,
      fastCharging: false,
      freeOnly: false,
      lessBusy: false,
      maxPrice: 0,
      minChargers: 0,
    });
  }

  function apply() {
    onChange(draft);
    onClose();
  }

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title={t("filters.title")}
      placement="bottom"
      showHandle
    >
      <div className="space-y-6">
        <Section title={t("filters.distance")}>
          <ChipGroup
            options={DISTANCE_OPTIONS.map((km) => ({
              value: km,
              label: km === 0 ? t("filters.any") : `${km} ${t("common.km")}`,
            }))}
            selected={draft.distanceKm}
            onSelect={(v) => setDraft({ ...draft, distanceKm: v })}
          />
        </Section>

        <Section title={t("filters.connector")}>
          <div className="flex flex-wrap gap-2">
            {ALL_CONNECTORS.map((c) => {
              const on = draft.connectorTypes.includes(c);
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => toggleConnector(c)}
                  className={cx(
                    "inline-flex h-10 items-center rounded-full border px-3.5 text-[13px] font-medium transition-colors",
                    on
                      ? "border-coral-600 bg-coral-50 text-coral-700"
                      : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50"
                  )}
                >
                  {c}
                </button>
              );
            })}
          </div>
        </Section>

        <Section title={t("filters.power")}>
          <ChipGroup
            options={POWER_OPTIONS.map((kw) => ({
              value: kw,
              label: kw === 0 ? t("filters.any") : `${kw}+ kW`,
            }))}
            selected={draft.minPowerKw}
            onSelect={(v) => setDraft({ ...draft, minPowerKw: v })}
          />
        </Section>

        <Section title={t("filters.price")}>
          <ChipGroup
            options={PRICE_OPTIONS.map((p) => ({
              value: p,
              label: p === 0 ? t("filters.any") : `≤ ₹${p}/kWh`,
            }))}
            selected={draft.maxPrice}
            onSelect={(v) => setDraft({ ...draft, maxPrice: v })}
          />
        </Section>

        <Section title={t("filters.chargers")}>
          <ChipGroup
            options={CHARGER_OPTIONS.map((n) => ({
              value: n,
              label: n === 0 ? t("filters.any") : `${n}+`,
            }))}
            selected={draft.minChargers}
            onSelect={(v) => setDraft({ ...draft, minChargers: v })}
          />
        </Section>

        <Section title={t("filters.availability")}>
          <ToggleRow
            label={t("station.status.available")}
            value={draft.availableOnly}
            onChange={(v) => setDraft({ ...draft, availableOnly: v })}
          />
          <ToggleRow
            label={t("filters.openNow")}
            value={draft.openNow}
            onChange={(v) => setDraft({ ...draft, openNow: v })}
          />
          <ToggleRow
            label={t("filters.fastCharging")}
            value={draft.fastCharging}
            onChange={(v) => setDraft({ ...draft, fastCharging: v })}
          />
          <ToggleRow
            label={t("filters.freeCharging")}
            value={draft.freeOnly}
            onChange={(v) => setDraft({ ...draft, freeOnly: v })}
          />
          <ToggleRow
            label={t("filters.lessBusy")}
            value={draft.lessBusy}
            onChange={(v) => setDraft({ ...draft, lessBusy: v })}
          />
        </Section>

        <div className="flex items-center justify-between gap-3 pt-2">
          <Button variant="ghost" size="md" onClick={reset}>
            {t("common.clearAll")}
          </Button>
          <Button variant="primary" size="md" onClick={apply} block>
            {t("common.apply")}
          </Button>
        </div>
      </div>
    </BottomSheet>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-[12px] font-semibold uppercase tracking-wider text-ink-600">
        {title}
      </h3>
      <div className="mt-2.5">{children}</div>
    </section>
  );
}

function ChipGroup({
  options,
  selected,
  onSelect,
}: {
  options: { value: number; label: string }[];
  selected: number;
  onSelect: (v: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onSelect(o.value)}
          className={cx(
            "inline-flex h-10 items-center rounded-full border px-3.5 text-[13px] font-medium transition-colors",
            selected === o.value
              ? "border-coral-600 bg-coral-50 text-coral-700"
              : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-[12px] border border-ink-100 bg-white px-3.5 py-3 hover:bg-ink-50">
      <span className="text-[14px] text-ink-800">{label}</span>
      <span
        role="switch"
        aria-checked={value}
        className={cx(
          "relative h-6 w-11 rounded-full transition-colors",
          value ? "bg-coral-600" : "bg-ink-200"
        )}
        onClick={() => onChange(!value)}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onChange(!value);
          }
        }}
      >
        <span
          className={cx(
            "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-card transition-transform",
            value ? "translate-x-5" : "translate-x-0.5"
          )}
        />
      </span>
    </label>
  );
}

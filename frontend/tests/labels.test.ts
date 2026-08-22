import { describe, expect, it } from "vitest"

import {
  categoryColors,
  categoryLabels,
  formatDateTime,
  priorityLabels,
  resolutionLabels,
  statusLabels,
} from "../lib/labels"

describe("formatDateTime", () => {
  it("renders a dash when there is no timestamp", () => {
    // Executive and management tables render optional timestamps -- started_at, closed_at --
    // straight into a cell. A null must become a dash, never "Invalid Date".
    expect(formatDateTime(null)).toBe("—")
  })

  it("formats in es-BO so the day comes before the month", () => {
    const formatted = formatDateTime("2026-03-04T15:30:00Z")
    // Asserted against Intl rather than a literal: the runner's timezone decides the clock
    // time, and pinning a string here would make this test fail on a machine in another zone
    // for a reason that has nothing to do with the code.
    expect(formatted).toBe(
      new Intl.DateTimeFormat("es-BO", { dateStyle: "short", timeStyle: "short" }).format(
        new Date("2026-03-04T15:30:00Z"),
      ),
    )
    expect(formatted).not.toBe("—")
  })
})

describe("label maps", () => {
  it("covers every enum value the API can return", () => {
    // A missing key renders as `undefined` in the staff UI rather than failing loudly, so the
    // maps are asserted whole.
    expect(Object.keys(categoryLabels).sort()).toEqual(Object.keys(categoryColors).sort())
    expect(categoryLabels.REPORTE_FRAUDE).toBe("Reporte de fraude")
    expect(priorityLabels.CRITICO).toBe("Crítico")
    expect(statusLabels.EN_ATENCION).toBe("En atención")
    expect(resolutionLabels.PENDIENTE_DOCUMENTACION).toBe("Pendiente de documentación")
    expect(Object.values(categoryColors).every((color) => /^#[0-9A-F]{6}$/i.test(color))).toBe(
      true,
    )
  })
})

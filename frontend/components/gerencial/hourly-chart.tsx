"use client"

import type { ManagementMetrics } from "@/lib/types"
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

export function HourlyChart({ data }: { data: ManagementMetrics["hourly"] }) {
  if (data.length === 0) {
    return <div className="grid h-full place-items-center text-sm text-gray-400">Sin datos</div>
  }
  return (
    <ResponsiveContainer height="100%" width="100%">
      <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid stroke="#F3F4F6" strokeDasharray="3 3" />
        <XAxis axisLine={false} dataKey="hour" tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} />
        <YAxis allowDecimals={false} axisLine={false} tick={{ fontSize: 11, fill: "#9CA3AF" }} tickLine={false} />
        <Tooltip formatter={(value) => [value, "Casos"]} />
        <Bar dataKey="cases" fill="#1168BD" maxBarSize={40} radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

"use client"

import { categoryColors, categoryLabels } from "@/lib/labels"
import type { Category, MetricSlice } from "@/lib/types"
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts"

export function CategoryChart({ data }: { data: MetricSlice[] }) {
  const chartData = data.map((item) => ({
    name: categoryLabels[item.name as Category] ?? item.name,
    value: item.value,
    color: categoryColors[item.name as Category] ?? "#6B7280",
  }))
  if (chartData.length === 0) {
    return <div className="grid h-full place-items-center text-sm text-gray-400">Sin datos</div>
  }
  return (
    <ResponsiveContainer height="100%" width="100%">
      <PieChart>
        <Pie
          data={chartData}
          dataKey="value"
          innerRadius={58}
          outerRadius={98}
          paddingAngle={3}
        >
          {chartData.map((entry) => (
            <Cell fill={entry.color} key={entry.name} />
          ))}
        </Pie>
        <Tooltip formatter={(value) => [value, "Casos"]} />
        <Legend formatter={(value) => <span className="text-xs text-gray-600">{value}</span>} />
      </PieChart>
    </ResponsiveContainer>
  )
}

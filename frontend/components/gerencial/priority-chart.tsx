"use client"

import { priorityLabels } from "@/lib/labels"
import type { MetricSlice, Priority } from "@/lib/types"
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

export function PriorityChart({ data }: { data: MetricSlice[] }) {
  const chartData = data.map((item) => ({ name: priorityLabels[item.name as Priority] ?? item.name, casos: item.value }))
  if (chartData.length === 0) return <div className="grid h-full place-items-center text-sm text-gray-400">Sin datos</div>
  return (
    <ResponsiveContainer height="100%" width="100%">
      <BarChart data={chartData} layout="vertical" margin={{ left: 12, right: 12 }}>
        <CartesianGrid horizontal={false} stroke="#F3F4F6" />
        <XAxis allowDecimals={false} axisLine={false} tick={{ fontSize: 11 }} tickLine={false} type="number" />
        <YAxis axisLine={false} dataKey="name" tick={{ fontSize: 11 }} tickLine={false} type="category" width={58} />
        <Tooltip formatter={(value) => [value, "Casos"]} />
        <Bar dataKey="casos" fill="#23A2D9" maxBarSize={28} radius={[0, 6, 6, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

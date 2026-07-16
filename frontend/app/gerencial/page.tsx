import { kpiData } from '@/lib/mock-data'
import { KpiCard } from '@/components/gerencial/kpi-card'
import { CategoryChart } from '@/components/gerencial/category-chart'
import { HourlyChart } from '@/components/gerencial/hourly-chart'
import { CasesTable } from '@/components/gerencial/cases-table'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Activity, AlertTriangle, Clock, Users } from 'lucide-react'

export default function GerencialPage() {
  return (
    <div className="max-w-7xl mx-auto flex flex-col gap-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          title="Total casos hoy"
          value={kpiData.totalToday}
          subtitle="Desde apertura"
          icon={<Users className="w-6 h-6" />}
          accentColor="#1168BD"
        />
        <KpiCard
          title="En atención"
          value={kpiData.inProgress}
          subtitle="Activos ahora"
          icon={<Activity className="w-6 h-6" />}
          accentColor="#23A2D9"
        />
        <KpiCard
          title="Tiempo promedio espera"
          value={`${kpiData.avgWaitMin} min`}
          subtitle="Últimas 8 horas"
          icon={<Clock className="w-6 h-6" />}
          accentColor="#F59E0B"
        />
        <KpiCard
          title="Casos críticos"
          value={kpiData.critical}
          subtitle="Requieren atención urgente"
          icon={<AlertTriangle className="w-6 h-6" />}
          accentColor="#EF4444"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Distribución por categoría</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[300px]">
              <CategoryChart />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Casos por hora (últimas 8 horas)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[300px]">
              <HourlyChart />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Cases table */}
      <Card>
        <CardHeader>
          <CardTitle>Últimos 10 casos</CardTitle>
        </CardHeader>
        <CasesTable />
      </Card>
    </div>
  )
}

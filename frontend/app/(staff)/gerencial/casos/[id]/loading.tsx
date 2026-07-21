export default function ManagerCaseLoading() {
  return (
    <div className="mx-auto max-w-6xl space-y-5" aria-label="Cargando expediente">
      <div className="h-5 w-40 animate-pulse rounded bg-gray-200" />
      <div className="h-44 animate-pulse rounded-2xl bg-gray-200" />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.7fr)]">
        <div className="h-96 animate-pulse rounded-2xl bg-white" />
        <div className="h-72 animate-pulse rounded-2xl bg-white" />
      </div>
    </div>
  )
}

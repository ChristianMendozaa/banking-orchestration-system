import Link from "next/link"

export default function NotFoundPage() {
  return (
    <main
      className="grid min-h-screen place-items-center bg-[#071426] p-6 text-center text-white"
      id="main-content"
    >
      <div>
        <h1 className="text-4xl font-bold">Página no encontrada</h1>
        <p className="mt-4 text-white/80">La dirección solicitada no está disponible.</p>
        <Link
          className="mt-7 inline-flex rounded-xl bg-[#1168BD] px-6 py-3 font-semibold focus:outline-none focus:ring-2 focus:ring-white"
          href="/"
        >
          Volver al inicio
        </Link>
      </div>
    </main>
  )
}

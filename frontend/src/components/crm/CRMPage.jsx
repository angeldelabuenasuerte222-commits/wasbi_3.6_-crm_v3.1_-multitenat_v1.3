import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { API } from "@/lib/api";

const FILTER_STATUS_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "nuevo", label: "Nuevo" },
  { value: "contactado", label: "Contactado" },
  { value: "en_proceso", label: "En proceso" },
  { value: "perdido", label: "Perdido" },
];

const DETAIL_STATUS_OPTIONS = [
  { value: "nuevo", label: "Nuevo" },
  { value: "contactado", label: "Contactado" },
  { value: "cerrado", label: "Cerrado" },
  { value: "descartado", label: "Descartado" },
  { value: "en_proceso", label: "En proceso" },
  { value: "perdido", label: "Perdido" },
];

const STATUS_STYLES = {
  nuevo: "text-[#22C55E] bg-[#22C55E]/10",
  contactado: "text-[#0EA5E9] bg-[#0EA5E9]/10",
  en_proceso: "text-[#F97316] bg-[#F97316]/10",
  perdido: "text-[#EF4444] bg-[#EF4444]/10",
  cerrado: "text-[#A855F7] bg-[#A855F7]/10",
  descartado: "text-[#F87171] bg-[#F87171]/10",
};

const formatDate = (isoString) => {
  if (!isoString) return "-";
  const date = new Date(isoString);
  return date.toLocaleString("es-MX", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export default function CRMPage() {
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [authError, setAuthError] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedLead, setSelectedLead] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [updating, setUpdating] = useState(false);
  const successTimerRef = useRef(null);

  const getAuthHeaders = () => ({ "x-admin-password": adminPassword });

  const handleUnauthorized = (message = "Contraseña incorrecta") => {
    setAuthError(message);
    setAdminPassword("");
    setSelectedLead(null);
    setLeads([]);
    setError("");
    setSuccessMessage("");
    setDetailLoading(false);
    setUpdating(false);
  };

  const loadLeads = async () => {
    if (!adminPassword) {
      return;
    }
    setLoading(true);
    setError("");
    setAuthError("");
    try {
      const params = {
        q: searchQuery || undefined,
        status: statusFilter || undefined,
        limit: 200,
      };
      const response = await axios.get(`${API}/leads`, {
        params,
        headers: getAuthHeaders(),
      });
      setLeads(response.data);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        handleUnauthorized("Contraseña incorrecta.");
        return;
      }
      setError("No fue posible cargar los leads.");
      console.error("CRM list error", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!adminPassword) return;
    loadLeads();
  }, [adminPassword, searchQuery, statusFilter, refreshKey]);

  const handleSearch = () => {
    setSearchQuery(searchText.trim());
  };

  const handleRefresh = () => {
    setRefreshKey((prev) => prev + 1);
  };

  const handlePasswordSubmit = (event) => {
    event.preventDefault();
    setAuthError("");
    const trimmed = passwordInput.trim();
    if (!trimmed) {
      setAuthError("Ingresa la contraseña para continuar.");
      return;
    }
    setAdminPassword(trimmed);
  };

  const handleLogout = () => {
    setAdminPassword("");
    setPasswordInput("");
    setSelectedLead(null);
    setLeads([]);
  };

  const handlePickLead = async (lead) => {
    if (!lead?.id) return;
    setDetailLoading(true);
    setError("");
    try {
      const { data } = await axios.get(`${API}/leads/${lead.id}`, {
        headers: getAuthHeaders(),
      });
      setSelectedLead(data);
      setNotesDraft(data.notes || "");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        handleUnauthorized("Contraseña incorrecta.");
        return;
      }
      setError("No fue posible obtener el detalle del lead.");
      console.error("CRM detail error", err);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleStatusChange = async (nextStatus) => {
    if (!selectedLead?.id) return;
    setUpdating(true);
    setError("");
    try {
      await axios.patch(
        `${API}/leads/${selectedLead.id}`,
        {
          status: nextStatus,
          notes: notesDraft,
        },
        { headers: getAuthHeaders() }
      );
      await handlePickLead(selectedLead);
      handleRefresh();
      showSuccess("Estado guardado");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        handleUnauthorized("Contraseña incorrecta.");
        return;
      }
      setError("No se pudo actualizar el estado.");
      console.error("CRM status update error", err);
    } finally {
      setUpdating(false);
    }
  };

  const handleSaveNotes = async () => {
    if (!selectedLead?.id) return;
    setUpdating(true);
    setError("");
    try {
      await axios.patch(
        `${API}/leads/${selectedLead.id}`,
        {
          notes: notesDraft,
        },
        { headers: getAuthHeaders() }
      );
      await handlePickLead(selectedLead);
      handleRefresh();
      showSuccess("Notas guardadas");
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        handleUnauthorized("Contraseña incorrecta.");
        return;
      }
      setError("No fue posible guardar las notas.");
      console.error("CRM notes update error", err);
    } finally {
      setUpdating(false);
    }
  };

  const showSuccess = (message) => {
    setSuccessMessage(message);
    if (successTimerRef.current) {
      window.clearTimeout(successTimerRef.current);
    }
    successTimerRef.current = window.setTimeout(() => {
      setSuccessMessage("");
    }, 3000);
  };

  useEffect(() => {
    return () => {
      if (successTimerRef.current) {
        window.clearTimeout(successTimerRef.current);
      }
    };
  }, []);

  if (!adminPassword) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center px-4">
        <div className="w-full max-w-md rounded-3xl border border-white/10 bg-[#0A0A0A] p-6 text-white shadow-2xl">
          <h1 className="text-2xl font-semibold">Acceso al CRM</h1>
          <p className="text-sm text-[#9CA3AF]">
            Protegemos esta vista con contraseña. Debes configurar la variable de entorno `ADMIN_PASSWORD`
            en tu backend para acceder. No hay contraseña por defecto.
          </p>
          <form onSubmit={handlePasswordSubmit} className="mt-5 space-y-4">
            <input
              type="password"
              placeholder="Contraseña"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              className="w-full rounded-2xl border border-white/10 bg-[#050505] px-4 py-3 focus:outline-none focus:border-[#22C55E]"
            />
            <button
              type="submit"
              className="w-full rounded-2xl bg-[#22C55E] py-3 text-sm font-semibold text-black transition hover:bg-[#16A34A]"
            >
              Entrar al CRM
            </button>
          </form>
          {authError && (
            <p className="mt-4 text-sm text-red-400">{authError}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] font-figtree text-white py-6 px-4 md:px-10">
      <header className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-sm text-[#9CA3AF]">CRM interno</p>
          <h1 className="text-3xl font-semibold text-white">Gestión de leads</h1>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={handleRefresh}
            className="px-4 py-2 rounded-xl bg-[#22C55E] text-black font-semibold hover:bg-[#16A34A] transition"
          >
            Refrescar
          </button>
          <button
            onClick={handleLogout}
            className="px-4 py-2 rounded-xl border border-white/20 text-white hover:border-white"
          >
            Cerrar sesión
          </button>
        </div>
      </header>

      <section className="bg-[#0A0A0A] border border-white/10 rounded-3xl p-5 mb-6 space-y-4">
        <div className="grid gap-4 md:grid-cols-[2fr,1fr,1fr]">
          <div>
            <label className="text-xs uppercase tracking-wider text-[#9CA3AF]">Buscar</label>
            <div className="mt-2 flex gap-2">
              <input
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="Nombre, teléfono o consulta"
                className="w-full rounded-2xl border border-white/10 bg-[#050505] px-4 py-2 focus:outline-none focus:border-[#22C55E]"
              />
              <button
                onClick={handleSearch}
                className="px-4 py-2 rounded-2xl bg-[#111111] border border-white/10 hover:border-[#22C55E] transition"
              >
                Buscar
              </button>
            </div>
          </div>
          <div>
            <label className="text-xs uppercase tracking-wider text-[#9CA3AF]">Filtrar por status</label>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="mt-2 w-full rounded-2xl border border-white/10 bg-[#050505] px-4 py-2 focus:outline-none focus:border-[#22C55E]"
              >
                {FILTER_STATUS_OPTIONS.map(({ value, label }) => (
                  <option key={value || "all"} value={value}>
                    {label}
                  </option>
                ))}
              </select>
          </div>
          <div className="flex flex-col justify-end">
            <span className="text-xs uppercase tracking-wider text-[#9CA3AF]">&nbsp;</span>
            <p className="text-xs text-[#9CA3AF]/80 mt-1">
              {loading ? "Cargando..." : `${leads.length} leads cargados`}
            </p>
          </div>
        </div>
      </section>

      {error && (
        <div className="mb-4 rounded-2xl border border-red-400/40 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {successMessage && (
        <div className="mb-4 rounded-2xl border border-emerald-400/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
          {successMessage}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 bg-[#0A0A0A] border border-white/10 rounded-3xl p-4">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wider text-[#9CA3AF]">
                <tr>
                  <th className="px-3 py-3">Nombre</th>
                  <th className="px-3 py-3">Teléfono</th>
                  <th className="px-3 py-3">Consulta</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3">Slug</th>
                  <th className="px-3 py-3">Creado</th>
                  <th className="px-3 py-3">Acción</th>
                </tr>
              </thead>
              <tbody>
                {leads.length === 0 && !loading ? (
                  <tr>
                    <td colSpan="7" className="px-3 py-6 text-center text-[#9CA3AF]">
                      No hay leads que coincidan.
                    </td>
                  </tr>
                ) : (
                  leads.map((lead) => (
                    <tr
                      key={lead.id}
                      className={`border-t border-white/5 hover:bg-white/5 transition cursor-pointer ${
                        selectedLead?.id === lead.id ? "bg-white/10" : ""
                      }`}
                    >
                      <td className="px-3 py-3 text-sm">{lead.nombre || "—"}</td>
                      <td className="px-3 py-3 text-sm">{lead.telefono || "—"}</td>
                      <td className="px-3 py-3 text-sm max-w-[220px] truncate">{lead.consulta || "—"}</td>
                      <td className="px-3 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                            STATUS_STYLES[lead.status] || "text-white/80 bg-white/10"
                          }`}
                        >
                          {lead.status || "nuevo"}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-sm">{lead.slug || "—"}</td>
                      <td className="px-3 py-3 text-sm">{formatDate(lead.created_at)}</td>
                      <td className="px-3 py-3 text-sm">
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            handlePickLead(lead);
                          }}
                          className="text-[#22C55E] hover:text-[#16A34A] text-xs font-semibold"
                        >
                          Ver detalle
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="lg:col-span-1 bg-[#0A0A0A] border border-white/10 rounded-3xl p-5">
          <h2 className="text-lg font-semibold text-white mb-2">Detalle del lead</h2>
          {detailLoading ? (
            <p className="text-sm text-[#9CA3AF]">Cargando detalle...</p>
          ) : selectedLead ? (
            <div className="space-y-4 text-sm text-[#E5E7EB]">
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Nombre</p>
                <p className="text-base font-semibold text-white">{selectedLead.nombre}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Teléfono</p>
                <p>{selectedLead.telefono}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Consulta</p>
                <p className="text-sm leading-relaxed text-[#D1D5DB]">{selectedLead.consulta}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Slug</p>
                <p>{selectedLead.slug}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Creado</p>
                <p>{formatDate(selectedLead.created_at)}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Session ID</p>
                <p className="text-xs text-[#D1D5DB]">{selectedLead.session_id || "—"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Status</p>
                <select
                  value={selectedLead.status || "nuevo"}
                  onChange={(e) => handleStatusChange(e.target.value)}
                  className="mt-1 w-full rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                  disabled={updating}
                >
                  {DETAIL_STATUS_OPTIONS.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-[#9CA3AF]">Notas</p>
                <textarea
                  rows={4}
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  placeholder="Notas internas..."
                  className="mt-1 w-full rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
                <button
                  onClick={handleSaveNotes}
                  disabled={updating}
                  className="mt-2 w-full rounded-2xl bg-[#22C55E] py-2 text-sm font-semibold text-black disabled:opacity-60"
                >
                  Guardar notas
                </button>
              </div>
              <p className="text-xs text-[#9CA3AF]">ID: {selectedLead.id}</p>
            </div>
          ) : (
            <p className="text-sm text-[#9CA3AF]">Selecciona un lead para ver su detalle.</p>
          )}
        </div>
      </div>
    </div>
  );
}

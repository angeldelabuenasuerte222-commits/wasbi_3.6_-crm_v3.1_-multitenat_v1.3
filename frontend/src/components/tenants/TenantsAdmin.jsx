import { useState } from "react";
import axios from "axios";
import { API } from "@/lib/api";

const emptyForm = {
  slug: "",
  business_name: "",
  phone: "",
  hours: "",
  address: "",
  avatar: "",
  image: "",
  greeting: "",
  system_prompt: "",
  admin_password: "",
  is_active: true,
};

const getApiDetail = (error) => {
  if (!axios.isAxiosError(error)) return "";
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? detail : "";
};

const getRequestErrorMessage = (error, fallback) => {
  if (!axios.isAxiosError(error)) {
    return fallback.defaultMessage;
  }

  if (!error.response) {
    return fallback.network || "No fue posible conectar con el backend.";
  }

  if (error.response.status === 401) {
    return fallback.unauthorized || "Contraseña global incorrecta.";
  }

  if (error.response.status === 400) {
    return getApiDetail(error) || fallback.badRequest || fallback.defaultMessage;
  }

  if (error.response.status === 404) {
    return getApiDetail(error) || fallback.notFound || fallback.defaultMessage;
  }

  if (error.response.status === 422) {
    return getApiDetail(error) || fallback.validation || fallback.defaultMessage;
  }

  return getApiDetail(error) || fallback.defaultMessage;
};

export default function TenantsAdmin() {
  const [adminPassword, setAdminPassword] = useState("");
  const [tenants, setTenants] = useState([]);
  const [selectedSlug, setSelectedSlug] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [toggleLoading, setToggleLoading] = useState("");
  const [detailLoading, setDetailLoading] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const authHeaders = () => ({
    "x-admin-password": adminPassword,
  });

  const handleLoadTenants = async () => {
    if (!adminPassword.trim()) {
      setError("Ingresa la contraseña global antes de cargar tenants.");
      return;
    }
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const response = await axios.get(`${API}/internal/tenants`, {
        headers: authHeaders(),
      });
      setTenants(response.data);
    } catch (err) {
      setMessage("");
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setTenants([]);
        setError("Contraseña global incorrecta.");
        return;
      }
      setError(
        getRequestErrorMessage(err, {
          defaultMessage: "No fue posible cargar tenants.",
        })
      );
      console.error("Tenants load error", err);
    } finally {
      setLoading(false);
    }
  };

  const handleFormChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const resetForm = () => {
    setForm(emptyForm);
    setSelectedSlug("");
  };

  const handleSelectTenant = async (tenant) => {
    if (!adminPassword.trim()) {
      setError("Ingresa la contraseña global antes de editar tenants.");
      return;
    }
    setDetailLoading(tenant.slug);
    setMessage("");
    setError("");
    try {
      const response = await axios.get(`${API}/internal/tenants/${tenant.slug}`, {
        headers: authHeaders(),
      });
      const detail = response.data;
      setSelectedSlug(detail.slug);
      setForm({
        slug: detail.slug,
        business_name: detail.business_name || "",
        phone: detail.phone || "",
        hours: detail.hours || "",
        address: detail.address || "",
        avatar: detail.avatar || "",
        image: detail.image || "",
        greeting: detail.greeting || "",
        system_prompt: detail.system_prompt || "",
        admin_password: "",
        is_active: detail.is_active ?? true,
      });
    } catch (err) {
      setError(
        getRequestErrorMessage(err, {
          unauthorized: "Contraseña global incorrecta.",
          notFound: `El tenant ${tenant.slug} ya no existe.`,
          defaultMessage: "No se pudo cargar el detalle del tenant.",
        })
      );
      console.error("Tenant detail error", err);
    } finally {
      setDetailLoading("");
    }
  };

  const handleToggleActive = async (tenant) => {
    if (!adminPassword.trim()) {
      setError("Ingresa la contraseña global antes de cambiar el estado.");
      return;
    }
    setToggleLoading(tenant.slug);
    setError("");
    setMessage("");
    try {
      await axios.patch(
        `${API}/internal/tenants/${tenant.slug}`,
        { is_active: !tenant.is_active },
        { headers: authHeaders() }
      );
      setMessage(`Tenant ${tenant.slug} ahora está ${!tenant.is_active ? "activo" : "inactivo"}.`);
      await handleLoadTenants();
    } catch (err) {
      setError(
        getRequestErrorMessage(err, {
          unauthorized: "Contraseña global incorrecta.",
          notFound: `El tenant ${tenant.slug} ya no existe.`,
          defaultMessage: "No se pudo actualizar el estado del tenant.",
        })
      );
      console.error("Toggle tenant error", err);
    } finally {
      setToggleLoading("");
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!adminPassword.trim()) {
      setError("Ingresa la contraseña global antes de guardar cambios.");
      return;
    }
    if (!form.slug.trim() || !form.business_name.trim()) {
      setError("El slug y el nombre del negocio son obligatorios.");
      return;
    }
    const trimmedPassword = form.admin_password.trim();
    if (!selectedSlug && trimmedPassword.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    setError("");
    setMessage("");
    setSubmitLoading(true);
    const payload = {
      business_name: form.business_name.trim(),
      phone: form.phone.trim(),
      hours: form.hours.trim(),
      address: form.address.trim(),
      avatar: form.avatar.trim(),
      image: form.image.trim(),
      greeting: form.greeting.trim(),
      system_prompt: form.system_prompt.trim(),
      is_active: form.is_active,
    };
    if (form.admin_password.trim()) {
      payload.admin_password = form.admin_password.trim();
    }
    try {
      if (selectedSlug) {
        await axios.patch(
          `${API}/internal/tenants/${selectedSlug}`,
          payload,
          { headers: authHeaders() }
        );
        setMessage("Tenant actualizado con éxito.");
      } else {
        await axios.post(
          `${API}/internal/tenants`,
          { ...payload, slug: form.slug.trim(), admin_password: trimmedPassword },
          { headers: authHeaders() }
        );
        setMessage("Tenant creado correctamente.");
      }
      resetForm();
      await handleLoadTenants();
    } catch (err) {
      setError(
        getRequestErrorMessage(err, {
          badRequest: "Revisa el slug y los datos del tenant.",
          validation: "Revisa los campos enviados antes de guardar.",
          defaultMessage: "Ocurrio un error guardando el tenant.",
        })
      );
      console.error("Tenant submit error", err);
    } finally {
      setSubmitLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] text-white px-4 py-6">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-wider text-[#9CA3AF]">Administración Multi-Tenant</p>
          <h1 className="text-3xl font-semibold">Panel interno de tenants</h1>
          <p className="text-xs text-[#9CA3AF]/80 max-w-2xl">
            Usa la contraseña global para trabajar con tenants reales. Las operaciones afectan el tenant document en Mongo,
            pero la compatibilidad legacy se mantiene mientras no desactives la vista global.
          </p>
        </header>

        <section className="rounded-3xl border border-white/10 bg-[#0A0A0A] p-5 shadow-xl">
          <div className="flex flex-wrap gap-3">
            <input
              type="password"
              placeholder="Contraseña global admin"
              value={adminPassword}
              onChange={(event) => setAdminPassword(event.target.value)}
              className="flex-1 min-w-[220px] rounded-2xl border border-white/10 bg-[#050505] px-4 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
            />
            <button
              onClick={handleLoadTenants}
              className="rounded-2xl bg-[#22C55E] px-4 py-2 text-sm font-semibold text-black"
              disabled={!adminPassword.trim() || loading}
            >
              {loading ? "Cargando..." : "Cargar tenants"}
            </button>
            <p className="text-xs text-[#9CA3AF]">
              {tenants.length} tenants cargados (modo multi-tenant real).
            </p>
          </div>
        </section>

        {error && (
          <div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}
        {message && (
          <div className="rounded-2xl border border-emerald-400/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
            {message}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1.3fr,0.7fr]">
          <div className="rounded-3xl border border-white/10 bg-[#0A0A0A] p-5 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Tenants registrados</h2>
              <button
                onClick={resetForm}
                className="text-xs text-[#9CA3AF] hover:text-white"
              >
                Limpiar formulario
              </button>
            </div>
            <div className="mt-4 space-y-3">
              {tenants.map((tenant) => (
                <div
                  key={tenant.slug}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/5 px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-semibold text-white">{tenant.business_name}</p>
                    <p className="text-xs text-[#9CA3AF]">
                      {tenant.slug} · {tenant.is_active ? "Activo" : "Inactivo"} ·{" "}
                      {tenant.has_password ? "Password segura" : "Sin password"}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleSelectTenant(tenant)}
                      disabled={detailLoading === tenant.slug}
                      className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-wider text-[#22C55E] disabled:opacity-40"
                    >
                      {detailLoading === tenant.slug ? "Cargando..." : "Editar"}
                    </button>
                    <button
                      onClick={() => handleToggleActive(tenant)}
                      disabled={toggleLoading === tenant.slug}
                      className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-wider text-[#9CA3AF] disabled:opacity-40"
                    >
                      {toggleLoading === tenant.slug ? "Actualizando..." : tenant.is_active ? "Desactivar" : "Activar"}
                    </button>
                  </div>
                </div>
              ))}
              {tenants.length === 0 && (
                <p className="text-xs text-[#9CA3AF]">No hay tenants cargados aún.</p>
              )}
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-[#0A0A0A] p-5 shadow-xl">
            <h2 className="text-lg font-semibold">
              {selectedSlug ? "Editar tenant" : "Crear tenant"}
            </h2>
            <p className="text-xs text-[#9CA3AF] mt-1">
              El slug debe ser la ruta pública (solo minúsculas y guiones). Cambia la contraseña sólo si necesitas resetearla.
            </p>
            <form onSubmit={handleSubmit} className="mt-4 space-y-3">
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Slug público
                </label>
                <input
                  type="text"
                  value={form.slug}
                  onChange={(event) => handleFormChange("slug", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                  disabled={Boolean(selectedSlug)}
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Nombre del negocio
                </label>
                <input
                  type="text"
                  value={form.business_name}
                  onChange={(event) => handleFormChange("business_name", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Teléfono
                </label>
                <input
                  type="text"
                  value={form.phone}
                  onChange={(event) => handleFormChange("phone", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Horarios
                </label>
                <input
                  type="text"
                  value={form.hours}
                  onChange={(event) => handleFormChange("hours", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Dirección
                </label>
                <input
                  type="text"
                  value={form.address}
                  onChange={(event) => handleFormChange("address", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Avatar URL
                </label>
                <input
                  type="text"
                  value={form.avatar}
                  onChange={(event) => handleFormChange("avatar", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Imagen de portada
                </label>
                <input
                  type="text"
                  value={form.image}
                  onChange={(event) => handleFormChange("image", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Saludo
                </label>
                <textarea
                  rows={2}
                  value={form.greeting}
                  onChange={(event) => handleFormChange("greeting", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  System prompt
                </label>
                <textarea
                  rows={6}
                  value={form.system_prompt}
                  onChange={(event) => handleFormChange("system_prompt", event.target.value)}
                  placeholder="Si lo dejas vacio al crear se usa el prompt seguro por defecto."
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
                <p className="text-xs text-[#9CA3AF]">
                  Controla el comportamiento interno del chatbot. En edicion, dejarlo vacio lo reinicia al prompt seguro por defecto.
                </p>
              </div>
              <div className="grid gap-2">
                <label className="text-[11px] uppercase tracking-[0.2em] text-[#9CA3AF]">
                  Contraseña admin (opcional en edición)
                </label>
                <input
                  type="password"
                  value={form.admin_password}
                  onChange={(event) => handleFormChange("admin_password", event.target.value)}
                  className="rounded-2xl border border-white/10 bg-[#050505] px-3 py-2 text-sm focus:outline-none focus:border-[#22C55E]"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(event) => handleFormChange("is_active", event.target.checked)}
                  className="h-4 w-4 rounded border border-white/20 bg-black text-[#22C55E]"
                />
                <label className="text-sm text-[#9CA3AF]">Tenant activo</label>
              </div>
              <button
                type="submit"
                disabled={submitLoading}
                className="w-full rounded-2xl bg-[#22C55E] py-3 text-sm font-semibold text-black transition hover:bg-[#16A34A] disabled:opacity-50"
              >
                {submitLoading ? "Guardando..." : selectedSlug ? "Actualizar tenant" : "Crear tenant"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

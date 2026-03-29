import { useState, useEffect } from "react";
import axios from "axios";
import { useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { User, Phone, MessageSquare, Clock } from "lucide-react";
import { API } from "@/lib/api";
import { normalizeSlug } from "@/lib/slug";

const getApiDetail = (error) => {
  if (!axios.isAxiosError(error)) return "";
  const detail = error.response?.data?.detail;
  return typeof detail === "string" ? detail : "";
};

const getDashboardError = (error, fallback) => {
  if (!axios.isAxiosError(error)) {
    return fallback.defaultMessage;
  }

  if (!error.response) {
    return fallback.network || "No fue posible conectar con el backend.";
  }

  if (error.response.status === 404) {
    return getApiDetail(error) || fallback.notFound || fallback.defaultMessage;
  }

  return getApiDetail(error) || fallback.defaultMessage;
};

export default function AdminDashboard() {
  const { slug: rawSlug } = useParams();
  const slug = normalizeSlug(rawSlug);
  const [password, setPassword] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [leads, setLeads] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [slugLoading, setSlugLoading] = useState(Boolean(slug));
  const [slugError, setSlugError] = useState("");

  useEffect(() => {
    if (!slug) {
      setSlugLoading(false);
      setSlugError("");
      return;
    }

    let cancelled = false;
    setSlugLoading(true);
    setSlugError("");

    axios.get(`${API}/business/${slug}`)
      .then(() => {
        if (!cancelled) {
          setSlugError("");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setSlugError(
          getDashboardError(err, {
            notFound: `No existe un tenant activo con el slug "${slug}".`,
            defaultMessage: "No fue posible validar el slug del CRM.",
          })
        );
      })
      .finally(() => {
        if (!cancelled) {
          setSlugLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (!slug) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center p-6 text-white">
        <div className="max-w-md bg-[#1A1A1A] border border-white/10 rounded-3xl p-6 text-center space-y-4">
          <h2 className="text-2xl font-semibold">Slug requerido</h2>
          <p className="text-sm text-[#9CA3AF]">
            La ruta del CRM para tenants necesita un slug valido (ej. <span className="text-[#22C55E] font-medium">/crm/cafe-minima</span>).
          </p>
          <p className="text-xs text-[#9CA3AF]/80">
            Manten la compatibilidad legacy usando la vista global en <span className="text-[#22C55E] font-semibold">/crm</span>.
          </p>
        </div>
      </div>
    );
  }

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await axios.get(`${API}/leads/${slug}`, {
        headers: {
          "x-admin-password": password
        }
      });
      setLeads(response.data);
      setIsAuthenticated(true);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setError("Contraseña incorrecta.");
      } else {
        setError(
          getDashboardError(err, {
            notFound: `El tenant "${slug}" ya no esta disponible.`,
            defaultMessage: "No fue posible cargar los leads.",
          })
        );
      }
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (isoString) => {
    const date = new Date(isoString);
    return date.toLocaleString('es-MX', { 
      day: '2-digit', 
      month: 'short', 
      year: 'numeric', 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  if (slugLoading) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center p-6 text-white">
        <div className="max-w-md rounded-3xl border border-white/10 bg-[#1A1A1A] p-6 text-center">
          Validando slug del CRM...
        </div>
      </div>
    );
  }

  if (slugError) {
    return (
      <div className="min-h-screen bg-[#050505] flex items-center justify-center p-6 text-white">
        <div className="max-w-md rounded-3xl border border-red-500/30 bg-[#1A1A1A] p-6 text-center space-y-4">
          <h2 className="text-2xl font-semibold">Slug no disponible</h2>
          <p className="text-sm text-[#9CA3AF]">{slugError}</p>
          <p className="text-xs text-[#9CA3AF]/80">
            Revisa la ruta o usa la vista global en <span className="text-[#22C55E] font-semibold">/crm</span>.
          </p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-[#050505] font-figtree flex items-center justify-center p-4">
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-[#1A1A1A] p-8 rounded-3xl border border-white/10 w-full max-w-sm shadow-2xl"
        >
          <h2 className="text-2xl text-white font-outfit font-semibold mb-2 text-center">Acceso Admin</h2>
          <p className="text-[#9CA3AF] text-sm text-center mb-8">Ingresa la contraseña para ver los leads de <span className="text-[#22C55E] font-medium">{slug}</span></p>
          
          <form onSubmit={handleLogin} className="flex flex-col gap-4">
            <div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Contraseña"
                className="w-full bg-[#0A0A0A] border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-[#22C55E] focus:ring-1 focus:ring-[#22C55E] transition-all text-center tracking-widest"
              />
            </div>
            
            {error && <p className="text-red-400 text-sm text-center">{error}</p>}
            
            <button
              type="submit"
              disabled={loading || !password}
              className="w-full bg-[#22C55E] hover:bg-[#16A34A] disabled:opacity-50 disabled:hover:bg-[#22C55E] text-black font-semibold rounded-xl py-3 mt-2 transition-all active:scale-[0.98]"
            >
              {loading ? "Verificando..." : "Ver Leads"}
            </button>
          </form>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505] font-figtree p-6 md:p-12">
      <div className="max-w-4xl mx-auto">
        <header className="flex items-center justify-between mb-8 border-b border-white/10 pb-6">
          <div>
            <h1 className="text-3xl font-outfit text-white font-bold tracking-tight">Leads Capturados</h1>
            <p className="text-[#9CA3AF] mt-1 flex items-center gap-2">
              <span className="bg-[#22C55E]/10 text-[#22C55E] px-2 py-0.5 rounded-md text-xs font-semibold uppercase tracking-wider">{slug}</span>
              <span>{leads.length} leads en total</span>
            </p>
          </div>
          <button 
            onClick={() => {
              setIsAuthenticated(false);
              setPassword("");
              setError("");
            }}
            className="text-sm text-[#9CA3AF] hover:text-white transition-colors"
          >
            Cerrar Sesión
          </button>
        </header>

        {leads.length === 0 ? (
          <div className="text-center py-20 bg-[#1A1A1A] rounded-3xl border border-white/5 border-dashed">
            <p className="text-[#9CA3AF]">Aún no hay leads capturados para este negocio.</p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {leads.map((lead, idx) => (
              <motion.div 
                key={idx}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.05 }}
                className="bg-[#1A1A1A] p-5 rounded-2xl border border-white/5 hover:border-[#22C55E]/30 transition-colors group relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 w-24 h-24 bg-[#22C55E]/5 rounded-bl-full -mr-8 -mt-8 pointer-events-none group-hover:bg-[#22C55E]/10 transition-colors"></div>
                
                <div className="flex items-start gap-4 relative z-10">
                  <div className="w-10 h-10 rounded-full bg-black border border-white/10 flex items-center justify-center shrink-0">
                    <User className="text-[#22C55E]" size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-white font-medium text-lg truncate">{lead.nombre}</h3>
                    
                    <div className="mt-4 space-y-2.5">
                      <div className="flex items-center gap-2.5 text-[#9CA3AF] text-sm">
                        <Phone size={14} />
                        <a href={`tel:${lead.telefono}`} className="hover:text-white transition-colors">{lead.telefono}</a>
                      </div>
                      
                      <div className="flex items-start gap-2.5 text-[#9CA3AF] text-sm">
                        <MessageSquare size={14} className="mt-0.5 shrink-0" />
                        <span className="leading-relaxed line-clamp-2" title={lead.consulta}>{lead.consulta}</span>
                      </div>
                    </div>
                    
                    <div className="mt-5 pt-4 border-t border-white/5 flex items-center gap-2 text-xs text-[#6B7280]">
                      <Clock size={12} />
                      {formatDate(lead.created_at)}
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

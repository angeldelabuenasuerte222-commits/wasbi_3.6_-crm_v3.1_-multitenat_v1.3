import { useEffect, useState, useRef } from "react";
import "@/App.css";
import axios from "axios";
import { ArrowUp, MapPin, Clock, MoreVertical, Phone, CheckCheck } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { BrowserRouter, Routes, Route, useParams } from "react-router-dom";
import { API } from "@/lib/api";

function InfoCard({ business }) {
  if (!business) return null;
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="bg-[#1A1A1A] border border-white/5 rounded-2xl p-4 flex flex-col gap-3 my-2 shadow-lg overflow-hidden max-w-[85%]"
      data-testid="info-widget-card"
    >
      <img src={business.image} alt="Business Storefront" className="w-full h-32 object-cover rounded-xl" />
      <div className="flex flex-col gap-2 mt-2 text-[#F3F4F6] text-[15px] font-figtree">
        <h3 className="font-semibold text-white text-lg">{business.business_name}</h3>
        <div className="flex items-center gap-2 text-[#9CA3AF]">
          <MapPin size={16} className="text-[#22C55E]" />
          <span>{business.address}</span>
        </div>
        <div className="flex items-center gap-2 text-[#9CA3AF]">
          <Clock size={16} className="text-[#22C55E]" />
          <span>{business.hours}</span>
        </div>
      </div>
    </motion.div>
  );
}

function ChatInterface() {
  const { slug } = useParams();
  const currentSlug = slug || "default";

  const [business, setBusiness] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [sessionId] = useState(`session_${Date.now()}_${Math.random().toString(36).substring(7)}`);
  
  const chatEndRef = useRef(null);

  useEffect(() => {
    // Fetch business details
    axios.get(`${API}/business/${currentSlug}`)
      .then(res => {
        setBusiness(res.data);
        setMessages([
          {
            id: "init",
            sender: "ai",
            text: res.data.greeting,
            isInfo: false
          },
          {
            id: "info",
            sender: "ai",
            isInfo: true
          }
        ]);
      })
      .catch(err => {
        console.error("Error fetching business config", err);
      });
  }, [currentSlug]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const uniqueId = () => Math.random().toString(36).substr(2, 9);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || !business) return;

    const userMsg = { id: uniqueId(), sender: "user", text: input.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setIsTyping(true);

    try {
      const response = await axios.post(`${API}/chat`, {
        text: userMsg.text,
        session_id: sessionId,
        slug: currentSlug
      });
      
      setMessages(prev => [
        ...prev,
        { id: uniqueId(), sender: "ai", text: response.data.reply }
      ]);
    } catch (error) {
      setMessages(prev => [
        ...prev,
        { id: uniqueId(), sender: "ai", text: "Lo siento, hubo un problema técnico." }
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  if (!business) {
    return <div className="min-h-screen bg-[#050505] flex items-center justify-center text-white">Cargando...</div>;
  }

  return (
    <div className="min-h-screen bg-[#050505] font-figtree flex justify-center w-full">
      <div className="max-w-md w-full h-[100dvh] flex flex-col relative bg-[#0A0A0A] overflow-hidden md:shadow-2xl md:border-x border-white/5">
        
        {/* Header */}
        <header className="h-16 flex items-center justify-between px-4 sticky top-0 z-50 backdrop-blur-xl bg-black/60 border-b border-white/5" data-testid="business-header">
          <div className="flex items-center gap-3">
            <img src={business.avatar} alt="Avatar" className="w-10 h-10 rounded-full object-cover border border-white/10" />
            <div className="flex flex-col">
              <h1 className="font-outfit text-white font-semibold text-lg leading-tight">{business.business_name}</h1>
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse"></div>
                <span className="text-[#22C55E] text-xs font-medium">Online</span>
              </div>
            </div>
          </div>
          <div className="flex gap-4 text-white/70">
            <Phone size={20} />
            <MoreVertical size={20} />
          </div>
        </header>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4 scroll-smooth">
          <AnimatePresence>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                className={`flex flex-col ${msg.sender === "user" ? "items-end" : "items-start"}`}
              >
                {msg.isInfo ? (
                  <InfoCard business={business} />
                ) : (
                  <div
                    data-testid={msg.sender === "ai" ? "chat-message-ai" : "chat-message-user"}
                    className={
                      msg.sender === "user"
                        ? "max-w-[85%] bg-[#22C55E] text-black px-4 py-3 rounded-2xl rounded-tr-sm self-end shadow-sm leading-relaxed text-[15px] font-medium"
                        : "max-w-[85%] bg-[#1A1A1A] text-[#F3F4F6] px-4 py-3 rounded-2xl rounded-tl-sm border border-white/5 shadow-sm leading-relaxed text-[15px]"
                    }
                  >
                    {msg.text}
                    {msg.sender === "user" && (
                      <span className="inline-flex ml-2 items-center text-black/60 translate-y-0.5">
                        <CheckCheck size={14} />
                      </span>
                    )}
                  </div>
                )}
              </motion.div>
            ))}
            
            {/* Typing Indicator */}
            {isTyping && (
              <motion.div
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                className="max-w-[85%] bg-[#1A1A1A] px-4 py-4 rounded-2xl rounded-tl-sm border border-white/5 shadow-sm self-start flex gap-1"
              >
                <motion.div animate={{ y: [0, -5, 0] }} transition={{ repeat: Infinity, duration: 0.6, delay: 0 }} className="w-1.5 h-1.5 bg-white/50 rounded-full" />
                <motion.div animate={{ y: [0, -5, 0] }} transition={{ repeat: Infinity, duration: 0.6, delay: 0.2 }} className="w-1.5 h-1.5 bg-white/50 rounded-full" />
                <motion.div animate={{ y: [0, -5, 0] }} transition={{ repeat: Infinity, duration: 0.6, delay: 0.4 }} className="w-1.5 h-1.5 bg-white/50 rounded-full" />
              </motion.div>
            )}
            <div ref={chatEndRef} />
          </AnimatePresence>
        </div>

        {/* Input Area */}
        <form onSubmit={sendMessage} className="p-4 sticky bottom-0 bg-black/80 backdrop-blur-xl border-t border-white/5 pb-safe relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Escribe un mensaje..."
            className="w-full bg-[#1A1A1A] border border-white/10 rounded-full pl-5 pr-12 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-[#22C55E] focus:ring-1 focus:ring-[#22C55E] transition-all text-[15px]"
            data-testid="chat-input-field"
          />
          <button
            type="submit"
            disabled={!input.trim() || isTyping}
            className="absolute right-5 top-5 h-9 w-9 bg-[#22C55E] hover:bg-[#16A34A] disabled:opacity-50 disabled:hover:bg-[#22C55E] text-black rounded-full flex items-center justify-center transition-transform active:scale-95 cursor-pointer"
            aria-label="Send message"
            data-testid="send-message-button"
          >
            <ArrowUp size={18} className="stroke-[2.5]" />
          </button>
        </form>

      </div>
    </div>
  );
}

import AdminDashboard from "./AdminDashboard";
import CRMPage from "@/components/crm/CRMPage";
import TenantsAdmin from "@/components/tenants/TenantsAdmin";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/crm" element={<CRMPage />} /> {/* Global CRM */}
        <Route path="/crm/:slug" element={<AdminDashboard />} /> {/* Business-specific leads */}
        <Route path="/internal/tenants" element={<TenantsAdmin />} /> {/* Panel interno multi-tenant */}
        <Route path="/:slug?" element={<ChatInterface />} />
      </Routes>
    </BrowserRouter>
  );
}

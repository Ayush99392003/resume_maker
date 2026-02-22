import React, { useState, useEffect } from 'react';
import axios from 'axios';
import AceEditor from 'react-ace';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Sparkles, FileText, Send, Download, Settings, 
  ChevronRight, Layout, Code2, Eye, MessageSquare, 
  RefreshCw, CheckCircle2, AlertCircle, Target, 
  BarChart3, Hash, ShieldAlert, Zap, Layers
} from 'lucide-react';

import 'ace-builds/src-noconflict/mode-latex';
import 'ace-builds/src-noconflict/theme-github_dark';
import 'ace-builds/src-noconflict/ext-language_tools';

const API_BASE = '/api';

function App() {
  const [isStarted, setIsStarted] = useState(true);
  const [loading, setLoading] = useState(false);
  const [bio, setBio] = useState('');
  const [latexCode, setLatexCode] = useState('');
  const [pdfUrl, setPdfUrl] = useState('');
  const [summary, setSummary] = useState('');
  const [activeTab, setActiveTab] = useState('preview');
  const [messages, setMessages] = useState([
    { 
      role: 'assistant', 
      content: "👋 Welcome! I'm your Gemini-powered Resume Architect. Paste your bio or career summary to begin building your professional LaTeX resume.",
      status: 'success'
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  
  const [jd, setJd] = useState('');
  const [atsScore, setAtsScore] = useState(null);
  const [scoringLoading, setScoringLoading] = useState(false);
  
  const [health, setHealth] = useState({ is_healthy: true, score: 100, issues: [] });
  const [selectedTemplate, setSelectedTemplate] = useState('classic');
  const [isInitialized, setIsInitialized] = useState(false);

  const [sections, setSections] = useState([]);
  const [selectedSection, setSelectedSection] = useState('Full Document');

  useEffect(() => {
    if (latexCode) {
      const delayDebounceFn = setTimeout(() => {
        validateCode();
        fetchSections();
      }, 1000);
      return () => clearTimeout(delayDebounceFn);
    }
  }, [latexCode]);

  const validateCode = async () => {
    try {
      const resp = await axios.post(`${API_BASE}/validate`, { latex_code: latexCode });
      setHealth(resp.data);
    } catch (e) {}
  };

  const fetchSections = async () => {
    try {
      const resp = await axios.post(`${API_BASE}/sections`, { latex_code: latexCode });
      setSections(['Full Document', ...resp.data.sections]);
    } catch (e) {}
  };

  const handleScore = async () => {
    if (!jd.trim()) return;
    setScoringLoading(true);
    try {
      // We need to extract plain text from LaTeX for better scoring
      // For now, we'll send the LaTeX but in a real app, a parser would clean it
      const resp = await axios.post(`${API_BASE}/score`, {
        resume_text: latexCode,
        job_description: jd
      });
      setAtsScore(resp.data);
    } catch (e) {
      console.error("Scoring failed", e);
    } finally {
      setScoringLoading(false);
    }
  };

  const handleInitOrEdit = async () => {
    if (!inputValue.trim()) return;
    const msg = { role: 'user', content: inputValue };
    setMessages(prev => [...prev, msg]);
    setInputValue('');
    setLoading(true);

    try {
      if (!isInitialized) {
        setBio(msg.content);
        const resp = await axios.post(`${API_BASE}/generate`, { 
          bio: msg.content, 
          template_name: selectedTemplate 
        });
        setLatexCode(resp.data.latex_code);
        setSummary(resp.data.summary);
        updatePdf(resp.data.pdf_base64);
        setIsInitialized(true);
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: `Initial resume engineered! You can now refine it via chat. I'll provide multiple variants for your edits.`, 
          status: 'success' 
        }]);
      } else {
        // Multi-turn Refinement Loop
        const target = selectedSection === 'Full Document' ? null : selectedSection;
        const resp = await axios.post(`${API_BASE}/propose`, {
          current_latex: latexCode,
          command: msg.content,
          section_name: target
        });
        
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          type: 'proposal',
          sessionId: resp.data.session_id,
          variants: resp.data.variants,
          targetSection: selectedSection,
          content: `I've generated a few variations for your edit in ${selectedSection}. Which one do you prefer?`,
          status: 'success' 
        }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Action failed. Please try again.', 
        status: 'error' 
      }]);
    } finally {
      setLoading(false);
    }
  };

  const applyVariant = async (sessionId, variantId, targetSection) => {
    setLoading(true);
    try {
      const target = targetSection === 'Full Document' ? null : targetSection;
      const resp = await axios.post(`${API_BASE}/apply`, {
        session_id: sessionId,
        variant_id: variantId,
        current_latex: latexCode,
        section_name: target
      });
      setLatexCode(resp.data.latex_code);
      updatePdf(resp.data.pdf_base64);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `Applied! ${resp.data.summary}`, 
        status: 'success' 
      }]);
    } catch (e) {
       setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Failed to apply variant.', 
        status: 'error' 
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/compile`, {
        latex_code: latexCode
      });
      updatePdf(resp.data.pdf_base64);
    } catch (e) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Manual compile failed. Check your LaTeX syntax.', 
        status: 'error' 
      }]);
    } finally {
      setLoading(false);
    }
  };

  const [snapshots, setSnapshots] = useState([]);

  const handleSqueeze = async () => {
    setLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/squeeze`, { latex_code: latexCode });
      setLatexCode(resp.data.latex_code);
      updatePdf(resp.data.pdf_base64);
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: `Layout optimized! ${resp.data.summary}`, 
        status: 'success' 
      }]);
    } catch (e) {
      setMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'Optimization failed.', 
        status: 'error' 
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSnapshot = () => {
    const newSnapshot = {
      id: Date.now(),
      timestamp: new Date().toLocaleTimeString(),
      latex: latexCode,
      pdf: pdfUrl
    };
    setSnapshots(prev => [newSnapshot, ...prev].slice(0, 5));
    setMessages(prev => [...prev, { 
      role: 'assistant', 
      content: 'Snapshot saved! You can restore this version from the sidebar.', 
      status: 'success' 
    }]);
  };

  return (
    <div className="h-screen flex flex-col bg-[#fafafa] font-inter overflow-hidden">
      <nav className="h-24 glass fixed top-0 left-0 right-0 z-50 px-12 flex items-center justify-between border-b border-black/5">
        <div className="flex items-center gap-4 text-slate-950 font-black text-3xl tracking-tighter">
          <div className="p-2 bg-slate-900 rounded-xl text-white shadow-xl shadow-slate-900/20"><Sparkles size={24} /></div>
          <span>RM AI Artifacts</span>
        </div>
        <div className="flex items-center gap-8">
          <div className="flex bg-slate-100 p-2 rounded-2xl border border-black/5">
            <button onClick={() => setActiveTab('preview')} className={`flex items-center gap-3 px-8 py-2.5 rounded-xl transition-all font-black text-xs uppercase tracking-widest ${activeTab === 'preview' ? 'bg-white shadow-xl text-blue-600' : 'text-slate-500 hover:text-slate-800'}`}><Eye size={20} /> Preview</button>
            <button onClick={() => setActiveTab('code')} className={`flex items-center gap-3 px-8 py-2.5 rounded-xl transition-all font-black text-xs uppercase tracking-widest ${activeTab === 'code' ? 'bg-white shadow-xl text-blue-600' : 'text-slate-500 hover:text-slate-800'}`}><Code2 size={20} /> Source</button>
          </div>
          <button onClick={handleSnapshot} className="flex items-center gap-3 px-8 py-4 bg-white border border-black/10 hover:bg-slate-50 text-slate-950 rounded-2xl font-black text-xs uppercase tracking-widest transition-all shadow-sm"><FileText size={18} /> Snapshot</button>
          <button className="flex items-center gap-3 px-10 py-4 bg-slate-950 hover:bg-blue-600 text-white rounded-2xl font-black text-sm transition-all shadow-2xl hover:-translate-y-1"><Download size={22} /> Export PDF</button>
        </div>
      </nav>

      <main className="flex-1 mt-24 flex overflow-hidden">
        <div className="w-[540px] border-r border-black/5 bg-white flex flex-col z-20 shadow-[20px_0_100px_rgba(0,0,0,0.02)]">
          <div className="flex-1 overflow-auto p-12 space-y-14">
            {/* Page Squeezer */}
            <section className="space-y-6">
               <div className="flex items-center justify-between">
                 <h3 className="text-xs font-black uppercase tracking-[0.25em] text-slate-400 flex items-center gap-2"><Zap size={14} /> Power Tools</h3>
               </div>
               <button 
                onClick={handleSqueeze}
                disabled={loading}
                className="w-full py-6 bg-gradient-to-br from-blue-600 to-indigo-700 text-white rounded-[2rem] font-black text-sm uppercase tracking-widest shadow-xl shadow-blue-500/20 flex items-center justify-center gap-3 hover:-translate-y-1 transition-all disabled:opacity-50"
               >
                 {loading ? <RefreshCw className="animate-spin" size={18} /> : <><Layers size={18} /> Auto-Fit Page Squeezer</>}
               </button>
            </section>

            {/* Templates Selector */}
            <section className="space-y-6">
               <div className="flex items-center justify-between">
                 <h3 className="text-xs font-black uppercase tracking-[0.25em] text-slate-400 flex items-center gap-2"><Layout size={14} /> Design Template</h3>
               </div>
               <div className="flex gap-3">
                 {['classic', 'modern', 'executive'].map(t => (
                   <button key={t} onClick={() => setSelectedTemplate(t)} className={`flex-1 py-4 rounded-[1.25rem] border font-black text-[10px] uppercase tracking-widest transition-all ${selectedTemplate === t ? 'bg-slate-900 border-slate-900 text-white shadow-xl' : 'bg-slate-50 border-black/5 text-slate-500 hover:bg-slate-100'}`}>{t}</button>
                 ))}
               </div>
            </section>

            {snapshots.length > 0 && (
              <section className="space-y-6">
                 <h3 className="text-xs font-black uppercase tracking-[0.25em] text-slate-400 flex items-center gap-2"><BarChart3 size={14} /> History Snapshots</h3>
                 <div className="space-y-3">
                   {snapshots.map(s => (
                     <button key={s.id} onClick={() => { setLatexCode(s.latex); setPdfUrl(s.pdf); }} className="w-full p-4 bg-slate-50 border border-black/5 rounded-2xl flex items-center justify-between hover:bg-blue-50 transition-all">
                       <div className="flex items-center gap-3">
                         <div className="w-2 h-2 rounded-full bg-blue-600" />
                         <span className="text-xs font-bold text-slate-700">Snapshot {s.timestamp}</span>
                       </div>
                       <ChevronRight size={14} className="text-slate-300" />
                     </button>
                   ))}
                 </div>
              </section>
            )}

            {/* ATS Match Gauge */}
            <section className="space-y-8">
              <div className="flex items-center justify-between"><h3 className="text-xl font-black flex items-center gap-3"><Target className="text-blue-600" /> ATS Radar</h3></div>
              <div className="p-10 bg-slate-50 rounded-[3rem] border border-black/5 space-y-8 relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-32 h-32 bg-blue-600/5 rounded-full -mr-16 -mt-16 transition-all group-hover:scale-110" />
                {atsScore && (
                  <div className="space-y-8">
                    <div className="flex items-center gap-6">
                      <div className="flex items-center justify-center w-24 h-24 rounded-full border-8 border-blue-600 font-black text-blue-600 text-xl shadow-2xl shadow-blue-500/10 bg-white">
                        {Math.round(atsScore.total_score)}%
                      </div>
                      <div className="space-y-1">
                        <p className="font-black text-slate-900 text-sm">Match Confidence</p>
                        <p className="text-xs font-bold text-slate-400">Semantic: {Math.round(atsScore.semantic_match)}% | Keywords: {Math.round(atsScore.keyword_match)}%</p>
                      </div>
                    </div>
                    
                    <div className="space-y-4">
                       <p className="text-[10px] font-black uppercase tracking-[0.25em] text-slate-400">Keyword Analytics</p>
                       <div className="flex flex-wrap gap-2">
                         {atsScore.matched_keywords.map(kw => (
                           <span key={kw} className="px-3 py-1 bg-green-500/10 text-green-600 rounded-full text-[10px] font-black uppercase tracking-widest">+{kw}</span>
                         ))}
                         {atsScore.missing_keywords.map(kw => (
                           <span key={kw} className="px-3 py-1 bg-red-500/10 text-red-600 rounded-full text-[10px] font-black uppercase tracking-widest">-{kw}</span>
                         ))}
                       </div>
                    </div>
                  </div>
                )}
                {!atsScore && (
                  <div className="space-y-4">
                    <p className="text-[10px] font-black uppercase tracking-[0.25em] text-slate-400">Target Job Description</p>
                    <textarea value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste JD for precision match..." className="w-full h-44 bg-white border border-black/10 rounded-[2rem] p-6 text-sm font-bold focus:ring-4 focus:ring-blue-600/10 outline-none transition-all resize-none shadow-sm" />
                  </div>
                )}
                <button 
                  onClick={handleScore} 
                  disabled={scoringLoading}
                  className="w-full py-5 bg-slate-950 text-white rounded-[1.5rem] font-black text-sm transition-all hover:bg-blue-600 shadow-xl shadow-slate-950/10 flex items-center justify-center gap-2 tracking-widest uppercase disabled:opacity-50"
                >
                  {scoringLoading ? <RefreshCw className="animate-spin" size={14} /> : <>Optimize for JD <Zap size={14} /></>}
                </button>
              </div>
            </section>

            <section className="space-y-8">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-black uppercase tracking-[0.25em] text-slate-400 flex items-center gap-2"><MessageSquare size={14} /> AI Artifacts Chat</h3>
                {isInitialized && (
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">Target:</span>
                    <select 
                      value={selectedSection} 
                      onChange={(e) => setSelectedSection(e.target.value)}
                      className="bg-slate-50 border border-black/5 rounded-lg px-3 py-1 text-[10px] font-black uppercase tracking-widest outline-none focus:ring-2 focus:ring-blue-600/20"
                    >
                      {sections.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </div>
                )}
              </div>
              <div className="space-y-10 pb-10">
                {!isInitialized && (
                  <div className="flex flex-wrap gap-2 mb-4">
                    {['Professional', 'Academic', 'Modern', 'Executive'].map(mode => (
                      <button 
                        key={mode}
                        onClick={() => setInputValue(`Create a ${mode} resume based on: `)}
                        className="px-4 py-2 bg-slate-50 border border-black/5 rounded-full text-[10px] font-black uppercase tracking-widest text-slate-500 hover:bg-blue-600 hover:text-white transition-all"
                      >
                        {mode} Mode
                      </button>
                    ))}
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className="space-y-4">
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[90%] p-7 rounded-[2.5rem] text-sm font-bold leading-[1.6] shadow-xl ${m.role === 'user' ? 'bg-blue-600 text-white rounded-tr-none' : 'bg-slate-100 text-slate-800 rounded-tl-none border border-black/5'}`}>
                        {m.content}
                      </div>
                    </motion.div>
                    
                    {m.type === 'proposal' && (
                      <div className="grid grid-cols-1 gap-4 pl-4 border-l-4 border-slate-100 ml-4 py-2">
                        {m.variants.map(v => (
                          <motion.button 
                            key={v.id}
                            whileHover={{ x: 4 }}
                            onClick={() => applyVariant(m.sessionId, v.id, m.targetSection)}
                            className="bg-white border border-black/5 p-6 rounded-[2rem] text-left hover:shadow-2xl transition-all space-y-3 group"
                          >
                             <div className="flex items-center justify-between">
                               <span className="px-3 py-1 bg-slate-100 rounded-full text-[10px] font-black uppercase tracking-widest text-slate-500 group-hover:bg-blue-600 group-hover:text-white transition-all">{v.intent}</span>
                               <ChevronRight size={14} className="text-slate-300 group-hover:text-blue-600 transition-all" />
                             </div>
                             <p className="text-xs font-bold text-slate-600 leading-relaxed">{v.summary}</p>
                          </motion.button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
                {loading && (
                   <div className="flex justify-start">
                     <div className="px-8 py-6 bg-slate-50 rounded-[2rem] rounded-tl-none border border-black/5">
                        <div className="flex gap-2">
                           <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1 }} className="w-2 h-2 bg-blue-600 rounded-full" />
                           <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1, delay: 0.2 }} className="w-2 h-2 bg-blue-600 rounded-full" />
                           <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1, delay: 0.4 }} className="w-2 h-2 bg-blue-600 rounded-full" />
                        </div>
                     </div>
                   </div>
                )}
              </div>
            </section>
          </div>
          <div className="p-10 border-t border-black/5 bg-slate-50/30">
            <div className="relative group">
              <input value={inputValue} onChange={(e) => setInputValue(e.target.value)} onKeyPress={(e) => e.key === 'Enter' && handleInitOrEdit()} placeholder={isInitialized ? `Refining ${selectedSection}...` : "Paste bio to start..."} className="w-full pl-8 pr-24 py-7 bg-white border border-black/10 rounded-[2.5rem] shadow-2xl focus:ring-4 focus:ring-blue-600/10 outline-none transition-all font-black text-sm" />
              <button onClick={handleInitOrEdit} disabled={loading} className="absolute right-3 top-1/2 -translate-y-1/2 p-5 bg-blue-600 text-white rounded-2xl shadow-xl hover:scale-110 active:scale-90 transition-all disabled:opacity-50 disabled:scale-100"><Send size={24} /></button>
            </div>
          </div>
        </div>

        <div className="flex-1 bg-slate-100/30 flex flex-col relative overflow-hidden backdrop-blur-sm">
          <AnimatePresence mode="wait">
            {activeTab === 'preview' ? (
              <motion.div key="p" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 1.02 }} className="flex-1 p-16 overflow-auto flex justify-center">
                <div className="w-full max-w-[1050px] bg-white shadow-[0_60px_100px_-40px_rgba(0,0,0,0.1)] rounded-none border border-black/5 relative">
                  {pdfUrl ? <iframe src={`${pdfUrl}#toolbar=0`} className="w-full h-full border-none min-h-[1400px]" /> : <div className="h-full min-h-[1400px] flex items-center justify-center text-slate-200 font-black text-4xl animate-pulse">RENDER_ACTIVE</div>}
                </div>
              </motion.div>
            ) : (
              <motion.div key="c" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="flex-1 p-16 overflow-hidden">
                <div className="h-full w-full max-w-[1400px] mx-auto rounded-[4rem] shadow-2xl overflow-hidden bg-[#0c0c0d] border border-white/5 flex flex-col">
                   <div className="px-12 py-7 bg-white/5 flex items-center justify-between border-b border-white/5">
                     <div className="flex items-center gap-6">
                       <span className="text-[10px] font-black uppercase tracking-[0.4em] text-white/40">MASTER_SOURCE</span>
                       <div className={`flex items-center gap-2 px-4 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest ${health.is_healthy ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{health.is_healthy ? <Zap size={12} className="fill-current" /> : <ShieldAlert size={12} />} {health.is_healthy ? 'Stable' : `Warnings (${health.score})`}</div>
                     </div>
                     <div className="flex items-center gap-4">
                        <button 
                          onClick={handleSync}
                          disabled={loading}
                          className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-[10px] font-black uppercase tracking-widest transition-all flex items-center gap-2"
                        >
                          {loading ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                          Sync & Render
                        </button>
                        <div className="flex gap-2.5">
                          <div className="w-3 h-3 rounded-full bg-white/5" />
                          <div className="w-3 h-3 rounded-full bg-white/5" />
                          <div className="w-3 h-3 rounded-full bg-white/5" />
                        </div>
                     </div>
                   </div>
                   <div className="flex-1 relative flex">
                      <div className="w-20 bg-white/5 border-r border-white/5 flex flex-col items-center py-10 gap-8 text-white/20"><Layout size={20} /><Sparkles size={20} /><Settings size={20} /></div>
                      <div className="flex-1 overflow-hidden">
                        <AceEditor mode="latex" theme="github_dark" value={latexCode} onChange={setLatexCode} name="ae" width="100%" height="100%" fontSize={17} showPrintMargin={false} setOptions={{ useWorker: false }} style={{ background: 'transparent' }} className="p-10 font-mono" />
                      </div>
                   </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}
export default App;

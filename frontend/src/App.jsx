import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import AceEditor from 'react-ace';
import {
  Send, Download, Code2, Eye, RefreshCw, Plus, Trash2,
  LogOut, User, X, FileText, Target, Layers, RotateCcw, GripVertical
} from 'lucide-react';

import 'ace-builds/src-noconflict/mode-latex';
import 'ace-builds/src-noconflict/theme-github';
import 'ace-builds/src-noconflict/ext-language_tools';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

const PROVIDER_MODELS = {
  groq: ['openai/gpt-oss-120b', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'],
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1'],
  gemini: ['gemini-3.5-flash-lite', 'gemini-2.5-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
  anthropic: ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest'],
  azure: ['gpt-4o'],
  aws: ['anthropic.claude-3-5-sonnet-20240620-v1:0'],
};

function setAuthHeader(token) {
  if (token) axios.defaults.headers.common.Authorization = `Bearer ${token}`;
  else delete axios.defaults.headers.common.Authorization;
}

function errDetail(e, fallback) {
  const d = e?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d) return JSON.stringify(d);
  return e?.message || fallback;
}

function formatRelTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const diffSec = Math.floor((now - d) / 1000);
  if (diffSec < 60) return 'just now';
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function App() {
  const [authToken, setAuthToken] = useState(() => localStorage.getItem('rm_auth_token') || '');
  const [profile, setProfile] = useState(null);
  const [authMode, setAuthMode] = useState('login');
  const [authUser, setAuthUser] = useState('');
  const [authPass, setAuthPass] = useState('');
  const [authError, setAuthError] = useState('');
  const [authLoading, setAuthLoading] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(true);
  const [showProfile, setShowProfile] = useState(false);
  const [profileTab, setProfileTab] = useState('keys'); // keys | password
  // Per-provider credential settings
  const [providerTab, setProviderTab] = useState('groq');
  const [providerStatus, setProviderStatus] = useState({});
  const [providerDraft, setProviderDraft] = useState({});
  const [providerSaving, setProviderSaving] = useState(false);
  const [providerSaved, setProviderSaved] = useState(false);
  const [providerError, setProviderError] = useState('');
  const [pwdCurrent, setPwdCurrent] = useState('');
  const [pwdNew, setPwdNew] = useState('');
  const [pwdMsg, setPwdMsg] = useState('');
  const [saveError, setSaveError] = useState('');
  const [savingKeys, setSavingKeys] = useState(false);

  const [loading, setLoading] = useState(false);
  const [latexCode, setLatexCode] = useState('');
  const [pdfUrl, setPdfUrl] = useState('');
  const [activeTab, setActiveTab] = useState('preview');
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [jd, setJd] = useState('');
  const [atsScore, setAtsScore] = useState(null);
  const [scoringLoading, setScoringLoading] = useState(false);
  const [showAts, setShowAts] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState('modern');
  const [zones, setZones] = useState([]);
  const [zoneCatalog, setZoneCatalog] = useState([]);
  const [overleafUrl, setOverleafUrl] = useState('');
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('rm_session_id') || '');
  const [sessions, setSessions] = useState([]);
  const [provider, setProvider] = useState('groq');
  const [model, setModel] = useState('openai/gpt-oss-120b');
  const [providerInfo, setProviderInfo] = useState(null);
  // New-chat setup: either template URL/paste OR zone selection
  const [setupMode, setSetupMode] = useState(false);
  const [setupPath, setSetupPath] = useState('url'); // 'url' | 'zones'
  const [setupCatalog, setSetupCatalog] = useState([]);
  const [setupSelected, setSetupSelected] = useState([]);
  const [setupLatexPaste, setSetupLatexPaste] = useState('');
  const [setupLoading, setSetupLoading] = useState(false);
  const [setupError, setSetupError] = useState('');
  const [setupCustomDesc, setSetupCustomDesc] = useState('');
  const [selectedTargetZone, setSelectedTargetZone] = useState('auto');
  const [undoDepth, setUndoDepth] = useState(0);
  const [compileNote, setCompileNote] = useState('');
  const [compatNote, setCompatNote] = useState('');
  const [autoSyncing, setAutoSyncing] = useState(false);
  const chatEndRef = useRef(null);
  const pdfUrlRef = useRef('');
  const autoSyncSkipRef = useRef(false);

  const applyZoneState = (sessionOrCatalog, latex) => {
    if (sessionOrCatalog?.zones) {
      const order = sessionOrCatalog.zone_order || sessionOrCatalog.zones.map((z) => z.zone_no);
      const zmap = Object.fromEntries(sessionOrCatalog.zones.map((z) => [z.zone_no, z]));
      const cat = order.map((n) => zmap[n]).filter(Boolean).map((z) => ({
        zone_no: z.zone_no,
        description: z.description || `Zone ${z.zone_no}`,
        kind: z.kind,
      }));
      setZoneCatalog(cat);
      setZones(cat.map((z) => String(z.zone_no)));
    } else if (Array.isArray(sessionOrCatalog)) {
      setZoneCatalog(sessionOrCatalog);
      setZones(sessionOrCatalog.map((z) => String(z.zone_no ?? z)));
    }
    if (latex != null) setLatexCode(latex);
  };

  const hasKey = (p = provider) =>
    Boolean(providerStatus[p]?.configured || profile?.keys_configured?.[p]);

  const llmPayload = () => ({ provider, model });

  // Provider-specific field schemas
  const PROVIDER_FIELDS = {
    groq:      [{ k: 'api_key', label: 'API Key', type: 'password' }, { k: 'model', label: 'Model', type: 'text', placeholder: 'openai/gpt-oss-120b' }],
    openai:    [{ k: 'api_key', label: 'API Key', type: 'password' }, { k: 'model', label: 'Model', type: 'text', placeholder: 'gpt-4o' }],
    gemini:    [{ k: 'api_key', label: 'API Key', type: 'password' }, { k: 'model', label: 'Model', type: 'text', placeholder: 'gemini-3.5-flash-lite' }],
    anthropic: [{ k: 'api_key', label: 'API Key', type: 'password' }, { k: 'model', label: 'Model', type: 'text', placeholder: 'claude-3-5-sonnet-latest' }],
    azure: [
      { k: 'api_key',     label: 'API Key',         type: 'password' },
      { k: 'endpoint',    label: 'Endpoint URL',     type: 'text',     placeholder: 'https://<resource>.openai.azure.com/' },
      { k: 'deployment',  label: 'Deployment Name',  type: 'text',     placeholder: 'my-gpt4o-deployment' },
      { k: 'api_version', label: 'API Version',      type: 'text',     placeholder: '2024-02-01' },
      { k: 'model',       label: 'Model (optional)', type: 'text',     placeholder: 'gpt-4o' },
    ],
    aws: [
      { k: 'access_key_id',     label: 'Access Key ID',     type: 'password' },
      { k: 'secret_access_key', label: 'Secret Access Key', type: 'password' },
      { k: 'region',    label: 'Region',   type: 'text', placeholder: 'us-east-1' },
      { k: 'model_id',  label: 'Model ID', type: 'text', placeholder: 'amazon.nova-pro-v1:0' },
    ],
  };

  const loadProviderStatus = async () => {
    try {
      const resp = await axios.get(`${API_BASE}/auth/profile/providers`);
      const map = {};
      (resp.data.providers || []).forEach((p) => { map[p.provider] = p; });
      setProviderStatus(map);
    } catch (_) { /* ignore */ }
  };

  const saveProviderConfig = async (prov) => {
    setProviderError('');
    const draft = providerDraft[prov] || {};
    // Don't save if nothing was typed
    if (!Object.values(draft).some((v) => (v || '').trim())) {
      setProviderError('Fill in at least one field to save.');
      return;
    }
    setProviderSaving(true);
    try {
      const resp = await axios.put(`${API_BASE}/auth/profile/providers/${prov}`, draft);
      setProviderStatus((prev) => ({ ...prev, [prov]: resp.data }));
      setProviderDraft((prev) => ({ ...prev, [prov]: {} }));
      setProviderSaved(true);
      if (resp.data.model) {
        if (prov === provider) {
          setModel(resp.data.model);
        }
      }
      setTimeout(() => setProviderSaved(false), 1800);
    } catch (e) {
      setProviderError(errDetail(e, 'Could not save credentials'));
    } finally {
      setProviderSaving(false);
    }
  };

  const clearProviderConfig = async (prov) => {
    setProviderError('');
    try {
      const resp = await axios.delete(`${API_BASE}/auth/profile/providers/${prov}`);
      setProviderStatus((prev) => ({ ...prev, [prov]: resp.data }));
      setProviderDraft((prev) => ({ ...prev, [prov]: {} }));
    } catch (e) {
      setProviderError(errDetail(e, 'Could not clear credentials'));
    }
  };

  const changePassword = async () => {
    setPwdMsg('');
    try {
      await axios.post(`${API_BASE}/auth/profile/password`, {
        current_password: pwdCurrent,
        new_password: pwdNew,
      });
      setPwdCurrent('');
      setPwdNew('');
      setPwdMsg('Password updated.');
    } catch (e) {
      setPwdMsg(errDetail(e, 'Could not update password'));
    }
  };

  const updatePdf = useCallback((base64) => {
    if (!base64) return;
    if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
    pdfUrlRef.current = url;
    setPdfUrl(url);
  }, []);

  const applyProfile = (p) => {
    setProfile(p);
    if (p.default_provider) setProvider(p.default_provider);
    if (p.default_model) {
      const m = (p.default_model === 'llama-3.3-70b-versatile' || p.default_model === 'llama-3.1-70b-versatile' || p.default_model === 'gpt-oss-120b')
        ? 'openai/gpt-oss-120b'
        : p.default_model;
      setModel(m);
    }
  };

  const loadSessions = async () => {
    const resp = await axios.get(`${API_BASE}/sessions`);
    setSessions(resp.data.sessions || []);
  };

  const resetSetupState = () => {
    setSetupPath('url');
    setSetupCatalog([]);
    setSetupSelected([]);
    setSetupLatexPaste('');
    setSetupError('');
    setSetupCustomDesc('');
    setSetupLoading(false);
  };

  const compileAndRender = useCallback(async (latex, sid, { quiet = false, persist = !quiet } = {}) => {
    if (!(latex || '').trim()) return;
    if (!quiet) setLoading(true);
    else setAutoSyncing(true);
    try {
      const resp = await axios.post(`${API_BASE}/compile`, {
        latex_code: latex,
        session_id: sid || undefined,
      });
      const nextLatex = resp.data.latex_code || latex;
      if (nextLatex && nextLatex !== latex) {
        autoSyncSkipRef.current = true;
        setLatexCode(nextLatex);
      }
      if (resp.data.pdf_base64) {
        updatePdf(resp.data.pdf_base64);
        setCompileNote('');
      } else {
        setCompileNote(resp.data.compile_error || 'Compile failed');
      }
      if (persist && sid) {
        const put = await axios.put(`${API_BASE}/sessions/${sid}/latex`, {
          latex_code: nextLatex,
        });
        if (put.data?.latex_code && put.data.latex_code !== nextLatex) {
          autoSyncSkipRef.current = true;
          setLatexCode(put.data.latex_code);
        }
        if (put.data?.compat_notes?.length) {
          setCompatNote(
            `Adjusted for Windows Tectonic: ${put.data.compat_notes.join('; ')}`,
          );
        }
      }
      if (!quiet && resp.data.compile_error) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: resp.data.compile_error, status: 'error' },
        ]);
      }
    } catch (e) {
      const msg = errDetail(e, 'Compile failed');
      setCompileNote(msg);
      if (!quiet) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: msg, status: 'error' },
        ]);
      }
    } finally {
      if (!quiet) setLoading(false);
      else setAutoSyncing(false);
    }
  }, [updatePdf]);

  const enterChatFromSession = (s) => {
    setSessionId(s.session_id);
    localStorage.setItem('rm_session_id', s.session_id);
    setMessages(s.messages || []);
    setLatexCode(s.latex_code || '');
    applyZoneState(s, s.latex_code || '');
    setUndoDepth(s.turn_history?.length || 0);
    setPdfUrl('');
    setAtsScore(null);
    setCompileNote('');
    if (s.compat_banner) {
      setCompatNote(s.compat_banner);
    } else if (s.compat_notes?.length) {
      setCompatNote(`Adjusted for Windows Tectonic: ${s.compat_notes.join('; ')}`);
    } else {
      setCompatNote('');
    }
    setSetupMode(false);
    resetSetupState();
    if (s.latex_code) {
      compileAndRender(s.latex_code, s.session_id, { quiet: true });
    }
  };

  const startNewChatSetup = () => {
    setSetupMode(true);
    resetSetupState();
    setSessionId('');
    localStorage.removeItem('rm_session_id');
    setMessages([]);
    setLatexCode('');
    setPdfUrl('');
    setUndoDepth(0);
    setAtsScore(null);
    setZoneCatalog([]);
    setZones([]);
    setOverleafUrl('');
  };

  const hydrateSession = async (id) => {
    const resp = await axios.get(`${API_BASE}/sessions/${id}`);
    const s = resp.data;
    setSetupMode(false);
    resetSetupState();
    setSessionId(s.session_id);
    localStorage.setItem('rm_session_id', s.session_id);
    setMessages(s.messages || []);
    setLatexCode(s.latex_code || '');
    applyZoneState(s, s.latex_code || '');
    setUndoDepth(s.turn_history?.length || 0);
    setSelectedTemplate(s.template_name || 'classic');
    setProvider(s.active_provider || provider);
    const activeM = (s.active_model === 'llama-3.3-70b-versatile' || s.active_model === 'llama-3.1-70b-versatile' || s.active_model === 'gpt-oss-120b')
      ? 'openai/gpt-oss-120b'
      : (s.active_model || model);
    setModel(activeM);
    setOverleafUrl(s.source_url || '');
    if (s.latex_code) {
      compileAndRender(s.latex_code, s.session_id, { quiet: true, persist: false });
    }
  };

  const loadZonesCatalog = async (templateName = selectedTemplate) => {
    setSetupError('');
    setSetupLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/setup/import`, {
        template_name: templateName,
      });
      const catalog = resp.data.catalog || [];
      setSetupCatalog(catalog);
      setSetupSelected(catalog.map((z) => z.zone_no));
      setLatexCode(resp.data.latex_code || '');
    } catch (e) {
      setSetupError(errDetail(e, 'Could not load zones'));
    } finally {
      setSetupLoading(false);
    }
  };

  const toggleSetupZone = (zoneNo) => {
    setSetupSelected((prev) => (
      prev.includes(zoneNo)
        ? prev.filter((n) => n !== zoneNo)
        : [...prev, zoneNo]
    ));
  };

  const addSetupCustomZone = () => {
    const desc = (setupCustomDesc || '').trim();
    if (!desc) return;
    const tempNo = -(setupCatalog.length + 1);
    setSetupCatalog((prev) => [
      ...prev,
      { zone_no: tempNo, description: desc, kind: 'custom', _pending: true },
    ]);
    setSetupSelected((prev) => [...prev, tempNo]);
    setSetupCustomDesc('');
  };

  /** Path A: Overleaf URL or pasted .tex → session → chat + render */
  const startChatFromUrl = async () => {
    const url = (overleafUrl || '').trim();
    const latex = (setupLatexPaste || '').trim();
    if (!url && !latex) {
      setSetupError('Paste an Overleaf URL or full LaTeX source');
      return;
    }
    if (url && !latex && !/overleaf\.com|github\.com/i.test(url)) {
      setSetupError(
        'Link must be overleaf.com/latex/templates/… or a public project/GitHub URL',
      );
      return;
    }
    if (latex && !/\\documentclass/.test(latex)) {
      setSetupError('Pasted LaTeX should include \\documentclass{...}');
      return;
    }
    setSetupError('');
    setSetupLoading(true);
    try {
      let softenedLatex = latex;
      // Prefetch: URL download or paste preview compile (already Tectonic-softened)
      if (url && !latex) {
        const preview = await axios.post(`${API_BASE}/setup/import`, { url });
        softenedLatex = preview.data.latex_code || '';
        if (preview.data.compat_notes?.length) {
          setCompatNote(
            `Adjusted for Windows Tectonic: ${preview.data.compat_notes.join('; ')}`,
          );
        } else if (preview.data.warnings?.length) {
          setCompatNote(preview.data.warnings.join(' · '));
        }
        if (preview.data.compile_error) {
          setCompileNote(preview.data.compile_error);
        }
        if (preview.data.pdf_base64) updatePdf(preview.data.pdf_base64);
        if (softenedLatex) setLatexCode(softenedLatex);
      } else if (latex) {
        const preview = await axios.post(`${API_BASE}/setup/import`, { latex });
        softenedLatex = preview.data.latex_code || latex;
        if (softenedLatex) setLatexCode(softenedLatex);
        if (preview.data.compat_notes?.length) {
          setCompatNote(
            `Adjusted for Windows Tectonic: ${preview.data.compat_notes.join('; ')}`,
          );
        }
        if (preview.data.pdf_base64) updatePdf(preview.data.pdf_base64);
        if (preview.data.compile_error) setCompileNote(preview.data.compile_error);
      }
      const payload = { provider, model, template_name: selectedTemplate || 'modern' };
      if (url && !latex) payload.source_url = url;
      // Prefer softened source so session stores what actually compiles
      if (softenedLatex) payload.latex = softenedLatex;
      else if (latex) payload.latex = latex;
      const created = await axios.post(`${API_BASE}/sessions`, payload);
      enterChatFromSession(created.data);
      await loadSessions();
    } catch (e) {
      setSetupError(errDetail(e, 'Could not start from template URL/LaTeX'));
    } finally {
      setSetupLoading(false);
    }
  };

  /** Path B: bundled template + selected zones → session → chat */
  const startChatFromZones = async () => {
    if (!setupSelected.length) {
      setSetupError('Select at least one zone');
      return;
    }
    setSetupError('');
    setSetupLoading(true);
    try {
      const included = setupSelected.filter((n) => n > 0);
      const order = setupCatalog
        .map((z) => z.zone_no)
        .filter((n) => included.includes(n));
      const customs = setupCatalog
        .filter((z) => z._pending && setupSelected.includes(z.zone_no))
        .map((z) => z.description);

      const created = await axios.post(`${API_BASE}/sessions`, {
        template_name: selectedTemplate,
        provider,
        model,
        included_zone_nos: included,
        zone_order: order,
        custom_zones: customs,
      });
      enterChatFromSession(created.data);
      await loadSessions();
    } catch (e) {
      setSetupError(errDetail(e, 'Could not start from zone selection'));
    } finally {
      setSetupLoading(false);
    }
  };

  const addZone = async () => {
    if (!sessionId || setupMode) return;
    const desc = window.prompt('New zone description (e.g. Projects)', 'Projects');
    if (!desc) return;
    const resp = await axios.post(`${API_BASE}/sessions/${sessionId}/zones`, {
      description: desc,
    });
    applyZoneState(resp.data.session, resp.data.latex_code);
  };

  const removeZone = async (zoneNo) => {
    if (!sessionId || setupMode) return;
    if (!window.confirm(`Remove zone ${zoneNo}?`)) return;
    const resp = await axios.delete(`${API_BASE}/sessions/${sessionId}/zones/${zoneNo}`);
    applyZoneState(resp.data.session, resp.data.latex_code);
  };

  useEffect(() => {
    (async () => {
      try {
        const p = await axios.get(`${API_BASE}/providers`);
        setProviderInfo(p.data);
      } catch (_) { /* backend down */ }

      const token = localStorage.getItem('rm_auth_token');
      if (!token) {
        setBootstrapping(false);
        return;
      }
      setAuthHeader(token);
      try {
        const me = await axios.get(`${API_BASE}/auth/me`);
        setAuthToken(token);
        applyProfile(me.data);
        await loadSessions();
        await loadProviderStatus();
        const sid = localStorage.getItem('rm_session_id');
        if (sid) {
          try { await hydrateSession(sid); } catch (_) {
            localStorage.removeItem('rm_session_id');
            setSessionId('');
            setSetupMode(true);
            resetSetupState();
          }
        } else {
          setSetupMode(true);
          resetSetupState();
        }
      } catch (_) {
        localStorage.removeItem('rm_auth_token');
        setAuthToken('');
        setAuthHeader(null);
      } finally {
        setBootstrapping(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (!latexCode) return;
    const t = setTimeout(async () => {
      try {
        const s = await axios.post(`${API_BASE}/sections`, {
          latex_code: latexCode,
          session_id: sessionId || undefined,
        });
        if (s.data.catalog?.length) {
          setZoneCatalog(s.data.catalog);
          setZones(s.data.catalog.map((z) => String(z.zone_no)));
        } else {
          setZones(s.data.zones || []);
        }
      } catch (_) { /* ignore */ }
    }, 600);
    return () => clearTimeout(t);
  }, [latexCode, sessionId]);

  useEffect(() => {
    const savedModel = providerStatus[provider]?.model;
    const models = Array.from(new Set([
      ...(savedModel ? [savedModel] : []),
      ...(PROVIDER_MODELS[provider] || []),
    ]));
    if (models.length && !models.includes(model)) {
      setModel(savedModel || models[0]);
    }
  }, [provider, model, providerStatus]);

  const handleAuth = async () => {
    setAuthError('');
    setAuthLoading(true);
    try {
      const path = authMode === 'login' ? '/auth/login' : '/auth/register';
      const resp = await axios.post(`${API_BASE}${path}`, {
        username: authUser.trim(),
        password: authPass,
      });
      localStorage.setItem('rm_auth_token', resp.data.token);
      setAuthToken(resp.data.token);
      setAuthHeader(resp.data.token);
      applyProfile(resp.data.profile);
      setAuthPass('');
      await loadSessions();
      await loadProviderStatus();
      const hasAny = Object.values(resp.data.profile?.keys_configured || {}).some(Boolean);
      if (!hasAny) setShowProfile(true);
    } catch (e) {
      setAuthError(errDetail(e, 'Authentication failed'));
    } finally {
      setAuthLoading(false);
    }
  };

  const logout = async () => {
    try { await axios.post(`${API_BASE}/auth/logout`); } catch (_) { /* ignore */ }
    localStorage.removeItem('rm_auth_token');
    localStorage.removeItem('rm_session_id');
    setAuthToken('');
    setProfile(null);
    setAuthHeader(null);
    setShowProfile(false);
    setProviderStatus({});
    setProviderDraft({});
    setSessionId('');
    setSessions([]);
    setMessages([]);
    setLatexCode('');
    setPdfUrl('');
    setSetupMode(true);
    resetSetupState();
  };


  const patchModel = async (nextProvider, nextModel) => {
    setProvider(nextProvider);
    setModel(nextModel);
    if (!sessionId) return;
    try {
      await axios.patch(`${API_BASE}/sessions/${sessionId}/model`, {
        provider: nextProvider,
        model: nextModel,
      });
    } catch (_) { /* ignore */ }
  };

  const pushAssistant = (content, extra = {}) => {
    setMessages(prev => [...prev, { role: 'assistant', content, ...extra }]);
  };

  const handleChat = async () => {
    if (!inputValue.trim()) return;
    if (setupMode || !sessionId) {
      startNewChatSetup();
      return;
    }
    if (!hasKey()) {
      pushAssistant(`Add your ${provider.toUpperCase()} API key in Profile, then save.`, { status: 'error' });
      setShowProfile(true);
      return;
    }
    const sid = sessionId;
    const text = inputValue;
    const targetZoneToSend = selectedTargetZone;
    setSelectedTargetZone('auto'); // Reset for next interaction
    setInputValue('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/chat`, {
        session_id: sid,
        message: text,
        target_zone: targetZoneToSend,
        template_name: selectedTemplate,
        ...llmPayload(),
      });
      setLatexCode(resp.data.latex_code || '');
      if (resp.data.session) applyZoneState(resp.data.session, resp.data.latex_code);
      else if (resp.data.catalog) applyZoneState(resp.data.catalog, resp.data.latex_code);
      if (resp.data.pdf_base64) updatePdf(resp.data.pdf_base64);
      setProvider(resp.data.provider || provider);
      setModel(resp.data.model || model);
      if (resp.data.undo_depth != null) setUndoDepth(resp.data.undo_depth);
      const msg = {
        role: 'assistant',
        content: resp.data.reply,
        provider: resp.data.provider,
        model: resp.data.model,
        meta: {
          zones_changed: resp.data.zones_changed,
          resolved_zones: resp.data.resolved_zones,
        },
      };
      if (resp.data.proposals) {
        msg.type = 'proposal';
        msg.sessionId = resp.data.proposals.session_id;
        msg.variants = resp.data.proposals.variants;
      }
      setMessages(prev => [...prev, msg]);
      await loadSessions();
    } catch (e) {
      console.error('chat error', e.response?.status, e.response?.data);
      pushAssistant(errDetail(e, 'Chat failed'), { status: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleUndo = async () => {
    if (!sessionId || undoDepth === 0 || loading) return;
    setLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/sessions/${sessionId}/undo`);
      setLatexCode(resp.data.latex_code || '');
      if (resp.data.session?.messages) {
        setMessages(resp.data.session.messages);
      }
      if (resp.data.pdf_base64) {
        updatePdf(resp.data.pdf_base64);
      }
      applyZoneState(resp.data.session || resp.data, resp.data.latex_code);
      setUndoDepth(resp.data.undo_depth ?? Math.max(0, undoDepth - 1));
      if (resp.data.compile_error) {
        setCompileNote(resp.data.compile_error);
      } else {
        setCompileNote('');
      }
      await loadSessions();
    } catch (e) {
      pushAssistant(errDetail(e, 'Undo failed'), { status: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const applyVariant = async (proposalSessionId, variantId) => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/chat/apply`, {
        session_id: sessionId,
        proposal_session_id: proposalSessionId,
        variant_id: variantId,
        ...llmPayload(),
      });
      setLatexCode(resp.data.latex_code);
      if (resp.data.pdf_base64) updatePdf(resp.data.pdf_base64);
      if (resp.data.compile_error) {
        pushAssistant(
          `Applied: ${resp.data.summary}\n\n(Compile issue: ${resp.data.compile_error})`,
          { status: 'error' },
        );
      } else {
        pushAssistant(`Applied: ${resp.data.summary}`);
      }
    } catch (e) {
      pushAssistant(errDetail(e, 'Failed to apply variant'), { status: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    await compileAndRender(latexCode, sessionId, { quiet: false });
  };

  // Light auto-sync + render after latex edits / chat updates
  useEffect(() => {
    if (!sessionId || setupMode || !(latexCode || '').trim()) return;
    if (autoSyncSkipRef.current) {
      autoSyncSkipRef.current = false;
      return;
    }
    const t = setTimeout(() => {
      compileAndRender(latexCode, sessionId, { quiet: true });
    }, 1200);
    return () => clearTimeout(t);
  }, [latexCode, sessionId, setupMode, compileAndRender]);

  const handleSqueeze = async () => {
    if (!latexCode) return;
    setLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/squeeze`, { latex_code: latexCode, ...llmPayload() });
      setLatexCode(resp.data.latex_code);
      updatePdf(resp.data.pdf_base64);
      pushAssistant(resp.data.summary || 'Layout optimized.');
    } catch (e) {
      pushAssistant(errDetail(e, 'Optimization failed'), { status: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleScore = async () => {
    if (!jd.trim()) return;
    setScoringLoading(true);
    try {
      const resp = await axios.post(`${API_BASE}/score`, {
        resume_text: latexCode,
        job_description: jd,
        ...llmPayload(),
      });
      setAtsScore(resp.data);
    } catch (e) {
      pushAssistant(errDetail(e, 'ATS scoring failed'), { status: 'error' });
    } finally {
      setScoringLoading(false);
    }
  };

  const deleteSession = async (id, e) => {
    e.stopPropagation();
    await axios.delete(`${API_BASE}/sessions/${id}`);
    if (id === sessionId) {
      setSessionId('');
      localStorage.removeItem('rm_session_id');
      setMessages([]);
      setLatexCode('');
      setPdfUrl('');
    }
    await loadSessions();
  };

  const exportPdf = () => {
    if (!pdfUrl) return;
    const a = document.createElement('a');
    a.href = pdfUrl;
    a.download = 'resume.pdf';
    a.click();
  };

  const savedModel = providerStatus[provider]?.model;
  const modelOptions = Array.from(new Set([
    ...(savedModel ? [savedModel] : []),
    ...(PROVIDER_MODELS[provider] || []),
    ...(model ? [model] : []),
  ]));

  if (bootstrapping) {
    return (
      <div className="h-full flex items-center justify-center text-ink-500 text-sm">
        Loading…
      </div>
    );
  }

  if (!authToken || !profile) {
    return (
      <div className="min-h-full grid lg:grid-cols-2">
        <section className="relative hidden lg:flex flex-col justify-between p-14 bg-ink-950 text-ink-50 overflow-hidden">
          <div
            className="absolute inset-0 opacity-40"
            style={{
              backgroundImage:
                'radial-gradient(circle at 20% 20%, #2f6b52 0%, transparent 40%), radial-gradient(circle at 80% 80%, #3a3833 0%, transparent 35%)',
            }}
          />
          <div className="relative">
            <p className="text-xs tracking-[0.25em] uppercase text-ink-200/70 mb-6">Resume Maker</p>
            <h1 className="font-display text-4xl leading-tight max-w-md">
              Craft a precise LaTeX resume in conversation.
            </h1>
          </div>
          <p className="relative text-sm text-ink-200/80 max-w-sm leading-relaxed">
            Dynamic zones keep structure stable. Chat to update content. Switch models anytime — your profile and keys stay put.
          </p>
        </section>

        <section className="flex items-center justify-center p-8">
          <div className="w-full max-w-sm space-y-8">
            <div>
              <h2 className="font-display text-2xl text-ink-900">
                {authMode === 'login' ? 'Welcome back' : 'Create your profile'}
              </h2>
              <p className="mt-2 text-sm text-ink-500">
                Sign in to save API keys and resume chat history.
              </p>
            </div>

            <div className="flex border-b border-ink-200">
              {['login', 'register'].map((m) => (
                <button
                  key={m}
                  onClick={() => { setAuthMode(m); setAuthError(''); }}
                  className={`flex-1 pb-3 text-xs font-semibold uppercase tracking-wider ${
                    authMode === m ? 'text-accent border-b-2 border-accent' : 'text-ink-500'
                  }`}
                >
                  {m === 'login' ? 'Log in' : 'Register'}
                </button>
              ))}
            </div>

            <div className="space-y-3">
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-ink-500">Username</span>
                <input
                  value={authUser}
                  onChange={(e) => setAuthUser(e.target.value)}
                  autoComplete="username"
                  className="w-full px-3.5 py-2.5 rounded-md border border-ink-200 bg-white text-sm outline-none focus:border-accent"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-ink-500">Password</span>
                <input
                  type="password"
                  value={authPass}
                  onChange={(e) => setAuthPass(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleAuth()}
                  autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
                  className="w-full px-3.5 py-2.5 rounded-md border border-ink-200 bg-white text-sm outline-none focus:border-accent"
                />
              </label>
              {authError && (
                <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-md px-3 py-2">
                  {authError}
                </p>
              )}
              <button
                onClick={handleAuth}
                disabled={authLoading || !authUser.trim() || !authPass}
                className="w-full mt-2 py-2.5 rounded-md bg-accent text-white text-sm font-semibold hover:bg-accent-mid disabled:opacity-40"
              >
                {authLoading ? 'Working…' : authMode === 'login' ? 'Continue' : 'Create profile'}
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-ink-50">
      <header className="h-14 shrink-0 border-b border-ink-200 bg-white px-4 lg:px-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <span className="font-display text-lg text-ink-900">Resume Maker</span>
          <span className="hidden sm:inline text-ink-200">|</span>
          <span className="hidden sm:inline text-xs text-ink-500 truncate">{profile.username}</span>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-lg border border-ink-200 bg-white p-0.5 shadow-sm">
            <select
              value={provider}
              onChange={(e) => patchModel(e.target.value, (PROVIDER_MODELS[e.target.value] || [model])[0])}
              className="h-8 rounded-md border-0 bg-transparent px-2.5 text-xs font-semibold text-ink-800 capitalize focus:ring-0 cursor-pointer"
              title="Select AI Provider"
            >
              {Object.keys(PROVIDER_MODELS).map((p) => (
                <option key={p} value={p}>{p}{hasKey(p) ? ' ✓' : ' (key needed)'}</option>
              ))}
            </select>
            <span className="text-ink-200 text-xs select-none">/</span>
            <select
              value={model}
              onChange={(e) => patchModel(provider, e.target.value)}
              className="hidden md:block h-8 max-w-[180px] rounded-md border-0 bg-transparent px-2 text-xs text-ink-600 focus:ring-0 truncate cursor-pointer"
              title="Select Model"
            >
              {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div className="flex rounded-md border border-ink-200 overflow-hidden shadow-sm">
            <button
              onClick={() => setActiveTab('preview')}
              className={`h-9 px-3 text-xs font-medium flex items-center gap-1.5 transition-colors ${activeTab === 'preview' ? 'bg-ink-900 text-white' : 'bg-white text-ink-700 hover:bg-ink-50'}`}
            >
              <Eye size={14} /> Preview
            </button>
            <button
              onClick={() => setActiveTab('code')}
              className={`h-9 px-3 text-xs font-medium flex items-center gap-1.5 border-l border-ink-200 transition-colors ${activeTab === 'code' ? 'bg-ink-900 text-white' : 'bg-white text-ink-700 hover:bg-ink-50'}`}
            >
              <Code2 size={14} /> Code
            </button>
          </div>

          <button
            onClick={() => { setShowProfile(true); loadProviderStatus(); }}
            className={`h-9 px-3 rounded-md text-xs font-semibold flex items-center gap-1.5 border shadow-sm transition-colors ${
              Object.values(providerStatus).some((s) => s?.configured)
                ? 'border-accent/30 bg-accent-soft text-accent hover:bg-accent/20'
                : 'border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100'
            }`}
          >
            <User size={14} /> Profile
          </button>
          <button
            onClick={exportPdf}
            disabled={!pdfUrl}
            className="h-9 px-3 rounded-md bg-ink-900 text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-40 hover:bg-ink-800 transition-colors shadow-sm"
          >
            <Download size={14} /> PDF
          </button>
          <button onClick={logout} className="h-9 w-9 rounded-md border border-ink-200 text-ink-500 hover:text-ink-900 flex items-center justify-center shadow-sm transition-colors" title="Log out">
            <LogOut size={14} />
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex">
        {/* Sessions */}
        <aside className="w-56 shrink-0 border-r border-ink-200 bg-white flex flex-col">
          <div className="p-3 border-b border-ink-200">
            <button
              onClick={startNewChatSetup}
              className="w-full h-9 rounded-md bg-ink-900 text-white text-xs font-semibold flex items-center justify-center gap-1.5 hover:bg-ink-800 transition-colors shadow-sm"
            >
              <Plus size={14} /> New chat
            </button>
          </div>
          <div className="flex-1 overflow-auto p-2 space-y-1.5">
            {sessions.length === 0 && (
              <p className="text-xs text-ink-500 px-2 py-4">No chats yet.</p>
            )}
            {sessions.map((s) => {
              const relTime = formatRelTime(s.updated_at || s.created_at);
              const isCurrent = s.session_id === sessionId;
              return (
                <button
                  key={s.session_id}
                  onClick={() => hydrateSession(s.session_id)}
                  className={`w-full text-left rounded-lg p-2.5 transition-all group border ${
                    isCurrent
                      ? 'bg-accent/10 border-accent/40 shadow-xs'
                      : 'border-transparent hover:bg-ink-50 hover:border-ink-200/70'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs font-semibold text-ink-900 line-clamp-2 leading-snug">
                      {s.title}
                    </p>
                    <Trash2
                      size={13}
                      className="shrink-0 mt-0.5 text-ink-300 opacity-0 group-hover:opacity-100 hover:text-red-600 transition-opacity"
                      onClick={(e) => deleteSession(s.session_id, e)}
                      title="Delete chat"
                    />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-1 text-[10px] text-ink-500">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="rounded bg-ink-100 px-1.5 py-0.5 font-medium text-ink-700 uppercase tracking-wider text-[9px]">
                        {s.active_provider}
                      </span>
                      <span className="truncate max-w-[85px] opacity-70">
                        {s.active_model?.split('/')?.pop() || s.active_model}
                      </span>
                    </div>
                    {relTime && (
                      <span className="shrink-0 text-ink-400 text-[10px]">{relTime}</span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Chat / Setup */}
        <section className="w-[420px] shrink-0 border-r border-ink-200 bg-white flex flex-col min-h-0">
          {(setupMode || !sessionId) ? (
            <div className="flex-1 overflow-auto px-4 py-4 space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-500">
                  New chat setup
                </p>
                <p className="mt-1 text-sm text-ink-700">
                  Pick either a template URL/LaTeX paste, or zone selection — then start chat.
                </p>
                <div className="mt-3 grid grid-cols-2 gap-1.5">
                  <button
                    type="button"
                    onClick={() => { setSetupPath('url'); setSetupError(''); }}
                    className={`h-9 rounded-md text-[11px] font-semibold border ${
                      setupPath === 'url'
                        ? 'bg-ink-900 text-white border-ink-900'
                        : 'bg-white text-ink-600 border-ink-200'
                    }`}
                  >
                    Template URL
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSetupPath('zones');
                      setSetupError('');
                      if (!setupCatalog.length) loadZonesCatalog();
                    }}
                    className={`h-9 rounded-md text-[11px] font-semibold border ${
                      setupPath === 'zones'
                        ? 'bg-ink-900 text-white border-ink-900'
                        : 'bg-white text-ink-600 border-ink-200'
                    }`}
                  >
                    Zone selection
                  </button>
                </div>
              </div>

              {setupPath === 'url' && (
                <div className="space-y-3">
                  <div>
                    <p className="text-[11px] font-semibold text-ink-500 mb-1.5">Overleaf template URL</p>
                    <input
                      value={overleafUrl}
                      onChange={(e) => setOverleafUrl(e.target.value)}
                      placeholder="https://www.overleaf.com/latex/templates/name/id"
                      className="w-full h-9 rounded-md border border-ink-200 px-2 text-xs text-ink-800"
                    />
                    <p className="mt-1 text-[10px] text-ink-500 leading-snug">
                      Use a public gallery link (`/latex/templates/…`) or a public project/read link.
                      We download the zip (with .cls/.sty/images), convert zones, then render.
                      Private projects: paste .tex below instead.
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold text-ink-500 mb-1.5">
                      Or paste full LaTeX (no URL needed)
                    </p>
                    <textarea
                      value={setupLatexPaste}
                      onChange={(e) => setSetupLatexPaste(e.target.value)}
                      placeholder={'\\documentclass{article}\n\\begin{document}\n...\n\\end{document}'}
                      className="w-full h-36 rounded-md border border-ink-200 p-2 text-[11px] font-mono resize-none"
                    />
                    <p className="mt-1 text-[10px] text-ink-500 leading-snug">
                      Paste the whole <code>.tex</code>, then start — we convert zones and render the PDF.
                      Heavy packages (fontawesome / FiraMono) are softened for Windows Tectonic.
                    </p>
                  </div>
                  {setupError && <p className="text-xs text-red-600">{setupError}</p>}
                  <button
                    type="button"
                    onClick={startChatFromUrl}
                    disabled={setupLoading}
                    className="w-full h-10 rounded-md bg-accent text-white text-sm font-semibold disabled:opacity-40"
                  >
                    {setupLoading
                      ? 'Importing & rendering…'
                      : (setupLatexPaste || '').trim()
                        ? 'Start chat & render pasted LaTeX'
                        : 'Start chat from template URL'}
                  </button>
                </div>
              )}

              {setupPath === 'zones' && (
                <div className="space-y-3">
                  <div>
                    <p className="text-[11px] font-semibold text-ink-500 mb-1.5">Base template</p>
                    <div className="flex gap-1.5">
                      {['classic', 'modern', 'executive'].map((t) => (
                        <button
                          key={t}
                          type="button"
                          onClick={() => {
                            setSelectedTemplate(t);
                            setSetupCatalog([]);
                            setSetupSelected([]);
                            loadZonesCatalog(t);
                          }}
                          className={`flex-1 h-8 rounded-md text-[11px] font-semibold capitalize border ${
                            selectedTemplate === t
                              ? 'bg-ink-900 text-white border-ink-900'
                              : 'bg-white text-ink-600 border-ink-200'
                          }`}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-semibold text-ink-500 uppercase tracking-wider">
                      Include zones
                    </p>
                    <button
                      type="button"
                      onClick={loadZonesCatalog}
                      className="text-[11px] text-ink-500 hover:text-ink-800"
                    >
                      Reload
                    </button>
                  </div>
                  <div className="space-y-1.5 max-h-56 overflow-auto">
                    {setupCatalog.length === 0 && !setupLoading && (
                      <p className="text-xs text-ink-500">Loading zones…</p>
                    )}
                    {setupCatalog.map((z) => {
                      const checked = setupSelected.includes(z.zone_no);
                      return (
                        <label
                          key={z.zone_no}
                          className={`flex items-center gap-2 rounded-md border px-2.5 py-2 cursor-pointer ${
                            checked ? 'border-accent bg-accent-soft/40' : 'border-ink-200 bg-white'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleSetupZone(z.zone_no)}
                          />
                          <span className="text-xs font-semibold text-ink-900">
                            {z.zone_no > 0 ? `Zone ${z.zone_no}` : 'Custom'}
                          </span>
                          <span className="text-xs text-ink-600 truncate">{z.description}</span>
                        </label>
                      );
                    })}
                  </div>
                  <div className="flex gap-2">
                    <input
                      value={setupCustomDesc}
                      onChange={(e) => setSetupCustomDesc(e.target.value)}
                      placeholder="Add custom zone name…"
                      className="flex-1 h-9 rounded-md border border-ink-200 px-2 text-xs"
                      onKeyDown={(e) => e.key === 'Enter' && addSetupCustomZone()}
                    />
                    <button
                      type="button"
                      onClick={addSetupCustomZone}
                      className="h-9 px-3 rounded-md border border-ink-200 text-xs font-semibold"
                    >
                      Add
                    </button>
                  </div>
                  {setupError && <p className="text-xs text-red-600">{setupError}</p>}
                  <button
                    type="button"
                    onClick={startChatFromZones}
                    disabled={setupLoading || !setupSelected.length}
                    className="w-full h-10 rounded-md bg-accent text-white text-sm font-semibold disabled:opacity-40"
                  >
                    {setupLoading ? 'Starting…' : 'Start chat from zones'}
                  </button>
                </div>
              )}
            </div>
          ) : (
          <>
          <div className="px-4 py-3 border-b border-ink-200 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <p className="text-[11px] font-semibold text-ink-500 uppercase tracking-wider">Zones</p>
                <span className="text-[10px] text-ink-400 font-medium">
                  ({zoneCatalog.length || zones.length})
                </span>
              </div>
              <button
                type="button"
                onClick={addZone}
                className="text-[11px] font-semibold text-accent hover:underline flex items-center gap-0.5"
              >
                <Plus size={12} /> Add zone
              </button>
            </div>
            {zoneCatalog.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {zoneCatalog.map((z) => {
                  const isTarget = selectedTargetZone === String(z.zone_no) || selectedTargetZone === z.description;
                  return (
                    <button
                      key={z.zone_no}
                      type="button"
                      title="Click to remove zone"
                      onClick={() => removeZone(z.zone_no)}
                      className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] transition-colors ${
                        isTarget
                          ? 'border-accent bg-accent/15 text-accent font-semibold shadow-2xs'
                          : 'border-ink-200 bg-ink-50 text-ink-700 hover:border-red-300 hover:text-red-700'
                      }`}
                    >
                      <GripVertical size={9} className="opacity-40" />
                      <span className="font-semibold">Z{z.zone_no}</span>
                      <span className="truncate max-w-[8.5rem]">{z.description}</span>
                      <X size={9} className="opacity-50 hover:opacity-100 ml-0.5" />
                    </button>
                  );
                })}
              </div>
            ) : zones.length > 0 ? (
              <p className="text-[11px] text-ink-500">Zones: {zones.join(' · ')}</p>
            ) : null}
          </div>

          <div className="flex-1 overflow-auto px-4 py-4 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-500">Chat</p>
                {undoDepth > 0 && (
                  <span className="text-[10px] text-accent font-medium">
                    {undoDepth} undo{undoDepth > 1 ? 's' : ''}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={handleUndo}
                  disabled={loading || undoDepth === 0}
                  title={undoDepth > 0 ? `Undo last edit (${undoDepth} available)` : 'Nothing to undo'}
                  className="text-[11px] font-medium text-ink-600 hover:text-ink-900 disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1 px-2 py-1 rounded border border-ink-200 bg-white hover:bg-ink-50 transition-colors shadow-xs"
                >
                  <RotateCcw size={11} className={loading ? 'animate-spin' : ''} />
                  <span>Undo</span>
                  {undoDepth > 0 && (
                    <span className="ml-0.5 rounded-full bg-accent text-white px-1 text-[9px] font-bold leading-none py-0.5">
                      {undoDepth}
                    </span>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setShowAts((v) => !v)}
                  className="text-[11px] text-ink-500 hover:text-accent flex items-center gap-1 px-2 py-1 rounded hover:bg-ink-50 transition-colors"
                >
                  <Target size={12} /> ATS
                </button>
              </div>
            </div>

            {showAts && (
              <div className="rounded-md border border-ink-200 p-3 space-y-2 bg-ink-50">
                {atsScore && (
                  <p className="text-sm font-semibold text-ink-900">
                    Match {Math.round(atsScore.total_score)}%
                    <span className="ml-2 text-xs font-normal text-ink-500">
                      semantic {Math.round(atsScore.semantic_match)}% · keywords {Math.round(atsScore.keyword_match)}%
                    </span>
                  </p>
                )}
                <textarea
                  value={jd}
                  onChange={(e) => setJd(e.target.value)}
                  placeholder="Paste job description…"
                  className="w-full h-24 rounded-md border border-ink-200 p-2 text-xs resize-none outline-none focus:border-accent bg-white"
                />
                <button
                  onClick={handleScore}
                  disabled={scoringLoading}
                  className="w-full h-8 rounded-md bg-ink-900 text-white text-xs font-semibold disabled:opacity-40 shadow-xs hover:bg-ink-800 transition-colors"
                >
                  {scoringLoading ? 'Scoring…' : 'Score match'}
                </button>
              </div>
            )}

            {messages.map((m, i) => {
              const isUser = m.role === 'user';
              const timeStr = m.timestamp ? formatRelTime(m.timestamp) : '';
              return (
                <div key={m.id || i} className="space-y-1.5">
                  <div className={`flex items-center gap-1.5 text-[10px] text-ink-400 px-1 ${
                    isUser ? 'justify-end' : 'justify-start'
                  }`}>
                    <span className="font-semibold text-ink-600">{isUser ? 'You' : 'Assistant'}</span>
                    {timeStr && <span>· {timeStr}</span>}
                  </div>
                  <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[90%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed ${
                        isUser
                          ? 'bg-accent text-white shadow-xs'
                          : m.status === 'error'
                            ? 'bg-red-50 text-red-800 border border-red-100'
                            : 'bg-ink-50 text-ink-900 border border-ink-200 shadow-xs'
                      }`}
                    >
                      <div className="whitespace-pre-wrap">{m.content}</div>
                      {!isUser && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
                          {m.meta?.resolved_zones?.length ? (
                            <span className="inline-flex items-center gap-1.5 rounded bg-accent/15 px-2 py-0.5 font-medium text-accent">
                              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
                              Editing: {m.meta.resolved_zones.join(', ')}
                            </span>
                          ) : m.meta?.zones_changed?.length ? (
                            <span className="inline-flex items-center gap-1.5 rounded bg-accent/15 px-2 py-0.5 font-medium text-accent">
                              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                              Zones: {m.meta.zones_changed.join(', ')}
                            </span>
                          ) : null}
                          {(m.provider || m.model) && (
                            <span className="opacity-60">
                              {[m.provider, m.model].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                  {m.type === 'proposal' && m.variants && (
                    <div className="space-y-2 pl-2 border-l-2 border-ink-200">
                      {m.variants.map((v) => (
                        <button
                          key={v.id}
                          onClick={() => applyVariant(m.sessionId, v.id)}
                          className="w-full text-left rounded-md border border-ink-200 bg-white p-3 hover:border-accent shadow-xs transition-colors"
                        >
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-accent">{v.intent}</p>
                          <p className="mt-1 text-xs text-ink-700">{v.summary}</p>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            {loading && (
              <div className="text-xs text-ink-500 flex items-center gap-2 px-1">
                <RefreshCw size={12} className="animate-spin text-accent" /> Working…
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="border-t border-ink-200 p-3 space-y-2.5 bg-white">
            {/* Target Section Chip Selector with fade mask */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs mask-scroll-fade">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400 shrink-0">
                Target:
              </span>
              <button
                type="button"
                onClick={() => setSelectedTargetZone('auto')}
                title="Auto-detects target section from your instructions"
                className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  selectedTargetZone === 'auto'
                    ? 'bg-accent text-white shadow-xs'
                    : 'bg-ink-100 text-ink-600 hover:bg-ink-200'
                }`}
              >
                Auto
              </button>
              {zoneCatalog.length > 0 ? (
                zoneCatalog.map((z) => {
                  const label = z.description || `Zone ${z.zone_no}`;
                  const isSel = selectedTargetZone === String(z.zone_no) || selectedTargetZone === label;
                  return (
                    <button
                      key={z.zone_no}
                      type="button"
                      onClick={() => setSelectedTargetZone(isSel ? 'auto' : String(z.zone_no))}
                      title={`Target ${label}`}
                      className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                        isSel
                          ? 'bg-accent text-white shadow-xs'
                          : 'bg-ink-100 text-ink-600 hover:bg-ink-200'
                      }`}
                    >
                      {label}
                    </button>
                  );
                })
              ) : (
                ['Header', 'Education', 'Skills', 'Experience', 'Projects'].map((sec) => {
                  const isSel = selectedTargetZone.toLowerCase() === sec.toLowerCase();
                  return (
                    <button
                      key={sec}
                      type="button"
                      onClick={() => setSelectedTargetZone(isSel ? 'auto' : sec.toLowerCase())}
                      title={`Target ${sec}`}
                      className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                        isSel
                          ? 'bg-accent text-white shadow-xs'
                          : 'bg-ink-100 text-ink-600 hover:bg-ink-200'
                      }`}
                    >
                      {sec}
                    </button>
                  );
                })
              )}
              <button
                type="button"
                onClick={() => setSelectedTargetZone(selectedTargetZone === 'full_rewrite' ? 'auto' : 'full_rewrite')}
                title="Full Rewrite: applies instructions across the entire resume document"
                className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  selectedTargetZone === 'full_rewrite'
                    ? 'bg-amber-600 text-white shadow-xs'
                    : 'bg-amber-50 text-amber-800 border border-amber-200/60 hover:bg-amber-100'
                }`}
              >
                Full Rewrite
              </button>
            </div>

            <div className="space-y-1.5">
              <div className="flex rounded-lg border border-ink-200 bg-white focus-within:border-accent transition-colors shadow-xs">
                <textarea
                  rows={2}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleChat();
                    }
                  }}
                  placeholder={
                    selectedTargetZone !== 'auto'
                      ? `Instruct edit for ${selectedTargetZone}…`
                      : messages.some((m) => m.role === 'user')
                        ? 'Ask for an edit… (Enter to send, Shift+Enter for new line)'
                        : 'Paste your bio or describe updates to start…'
                  }
                  className="flex-1 resize-none p-2.5 text-xs outline-none bg-transparent"
                />
                <div className="flex flex-col justify-end p-2">
                  <button
                    onClick={handleChat}
                    disabled={loading || !inputValue.trim()}
                    className="h-8 w-8 rounded-md bg-accent text-white flex items-center justify-center disabled:opacity-40 hover:opacity-90 transition-opacity shadow-xs"
                    title="Send message (Enter)"
                  >
                    <Send size={14} />
                  </button>
                </div>
              </div>
              <div className="flex items-center justify-between text-[10px] text-ink-400 px-1">
                <span>⏎ Press Enter to send · Shift+Enter for new line</span>
                {inputValue.length > 0 && <span>{inputValue.length} chars</span>}
              </div>
            </div>

            <button
              onClick={handleSqueeze}
              disabled={loading || !latexCode}
              title="Tighten layout: compresses vertical spacing and margins to fit onto fewer pages"
              className="w-full h-7 rounded text-[11px] font-medium text-ink-500 hover:bg-ink-50 disabled:opacity-40 flex items-center justify-center gap-1.5 border border-ink-200/60 transition-colors shadow-2xs"
            >
              <Layers size={12} /> Tighten layout (fit to page)
            </button>
          </div>
          </>
          )}
        </section>

        {/* Artifact */}
        <section className="flex-1 min-w-0 bg-ink-100/60 flex flex-col">
          {(autoSyncing || compileNote || compatNote) && (
            <div className="border-b border-ink-200">
              {compatNote && (
                <div className="px-4 py-2 text-[11px] bg-sky-50 text-sky-950 border-b border-sky-100 flex items-start justify-between gap-2">
                  <span>{compatNote}</span>
                  <button
                    type="button"
                    className="shrink-0 text-sky-700/70 hover:text-sky-950"
                    onClick={() => setCompatNote('')}
                    aria-label="Dismiss compat note"
                  >
                    ×
                  </button>
                </div>
              )}
              {(autoSyncing || compileNote) && (
                <div className={`px-4 py-2 text-[11px] ${
                  compileNote ? 'bg-amber-50 text-amber-900' : 'bg-white text-ink-500'
                }`}>
                  {autoSyncing ? 'Auto-rendering preview…' : compileNote}
                </div>
              )}
            </div>
          )}
          {activeTab === 'preview' ? (
            <div className="flex-1 overflow-auto p-4 lg:p-6 flex flex-col items-center">
              <div className="w-full max-w-3xl flex items-center justify-between mb-2 px-1">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold text-ink-500 uppercase tracking-wider">
                    Document
                  </span>
                  {pdfUrl ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      Compiled PDF
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-full bg-ink-100 border border-ink-200 px-2 py-0.5 text-[10px] font-medium text-ink-500">
                      Draft
                    </span>
                  )}
                </div>
                {latexCode && (
                  <span className="text-[10px] text-ink-400">
                    {latexCode.split('\n').length} lines · LaTeX
                  </span>
                )}
              </div>
              <div className="w-full max-w-3xl bg-white border border-ink-200 shadow-md rounded-lg overflow-hidden min-h-[80vh]">
                {pdfUrl ? (
                  <iframe src={`${pdfUrl}#toolbar=0`} title="resume" className="w-full min-h-[80vh] border-0" />
                ) : (
                  <div className="min-h-[80vh] flex flex-col items-center justify-center text-ink-400 gap-2 p-8 text-center">
                    <FileText size={32} className="opacity-40" />
                    <p className="text-sm font-medium text-ink-600">Live preview will appear here</p>
                    <p className="text-xs text-ink-400 max-w-xs">Start a chat or import LaTeX to generate and inspect your compiled resume</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 p-4 min-h-0 flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-500">LaTeX source</p>
                <button
                  onClick={handleSync}
                  disabled={loading}
                  className="h-8 px-3 rounded-md bg-ink-900 text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-40"
                >
                  <RefreshCw size={12} className={loading || autoSyncing ? 'animate-spin' : ''} />
                  Sync & render
                </button>
              </div>
              <div className="flex-1 min-h-0 rounded-md overflow-hidden border border-ink-200 bg-white">
                <AceEditor
                  mode="latex"
                  theme="github"
                  value={latexCode}
                  onChange={setLatexCode}
                  name="latex-editor"
                  width="100%"
                  height="100%"
                  fontSize={14}
                  showPrintMargin={false}
                  setOptions={{ useWorker: false }}
                  className="font-mono"
                />
              </div>
            </div>
          )}
        </section>
      </div>

      {showProfile && (
        <div className="fixed inset-0 z-50 bg-ink-950/40 flex items-center justify-center p-4" onClick={() => setShowProfile(false)}>
          <div className="w-full max-w-lg bg-white rounded-lg border border-ink-200 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-ink-200">
              <div>
                <h3 className="font-display text-lg text-ink-900">Profile</h3>
                <p className="text-xs text-ink-500 mt-0.5">{profile.username}</p>
              </div>
              <button onClick={() => setShowProfile(false)} className="text-ink-400 hover:text-ink-900"><X size={18} /></button>
            </div>

            <div className="flex border-b border-ink-200 px-5">
              {[
                { id: 'keys', label: 'API keys' },
                { id: 'password', label: 'Password' },
              ].map((t) => (
                <button
                  key={t.id}
                  onClick={() => { setProfileTab(t.id); setSaveError(''); setPwdMsg(''); }}
                  className={`mr-4 py-3 text-xs font-semibold uppercase tracking-wider ${
                    profileTab === t.id ? 'text-accent border-b-2 border-accent' : 'text-ink-500'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {profileTab === 'keys' ? (
              <>
                {/* Provider tabs */}
                <div className="flex border-b border-ink-200 px-5 overflow-x-auto gap-3">
                  {Object.keys(PROVIDER_FIELDS).map((p) => {
                    const st = providerStatus[p];
                    return (
                      <button
                        key={p}
                        onClick={() => { setProviderTab(p); setProviderError(''); }}
                        className={`shrink-0 py-2.5 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 border-b-2 transition-colors ${
                          providerTab === p ? 'text-accent border-accent' : 'text-ink-500 border-transparent'
                        }`}
                      >
                        {p}
                        {st?.configured
                          ? <span className="w-1.5 h-1.5 rounded-full bg-accent inline-block" />
                          : <span className="w-1.5 h-1.5 rounded-full bg-ink-200 inline-block" />}
                      </button>
                    );
                  })}
                </div>

                {/* Fields for selected provider */}
                <div className="p-5 space-y-4 max-h-[52vh] overflow-auto">
                  {(() => {
                    const p = providerTab;
                    const st = providerStatus[p];
                    const draft = providerDraft[p] || {};
                    const fields = PROVIDER_FIELDS[p] || [];
                    return (
                      <>
                        <div className="flex items-center justify-between">
                          <p className="text-xs text-ink-500 leading-relaxed flex items-center flex-wrap gap-1.5">
                            {st?.configured
                              ? <span className="text-accent font-semibold">✓ Configured</span>
                              : <span className="text-amber-700 font-semibold">Not configured</span>}
                            {st?.hint && <span className="text-ink-400 font-mono text-[10px]">{st.hint}</span>}
                            {st?.model && (
                              <span className="text-accent font-mono text-[10px] bg-accent/10 px-1.5 py-0.5 rounded font-medium">
                                model: {st.model}
                              </span>
                            )}
                          </p>
                          {st?.configured && (
                            <button
                              type="button"
                              onClick={() => clearProviderConfig(p)}
                              className="text-[10px] font-semibold uppercase tracking-wide text-ink-400 hover:text-red-600"
                            >
                              Clear all
                            </button>
                          )}
                        </div>

                        <p className="text-[11px] text-ink-400">
                          Leave blank to keep saved values. Only filled fields are updated.
                        </p>

                        {fields.map((f) => {
                          const isPassword = f.type === 'password';
                          const savedVal = f.k === 'model' ? (st?.model || '') : (st?.[f.k] || '');
                          const displayVal = draft[f.k] !== undefined ? draft[f.k] : (isPassword ? '' : savedVal);
                          const placeholderText = isPassword
                            ? (st?.configured ? '•••••••• (paste to replace)' : (f.placeholder || ''))
                            : (savedVal || f.placeholder || '');

                          return (
                            <label key={f.k} className="block space-y-1.5">
                              <div className="flex items-center justify-between">
                                <span className="text-xs font-medium text-ink-600">{f.label}</span>
                                {!isPassword && savedVal && (
                                  <span className="text-[10px] text-ink-400 font-mono">Current: {savedVal}</span>
                                )}
                              </div>
                              <input
                                type={f.type}
                                autoComplete={isPassword ? 'new-password' : 'off'}
                                autoCorrect="off"
                                spellCheck={false}
                                name={`${p}-${f.k}`}
                                value={displayVal}
                                onChange={(e) =>
                                  setProviderDraft((prev) => ({
                                    ...prev,
                                    [p]: { ...(prev[p] || {}), [f.k]: e.target.value },
                                  }))
                                }
                                placeholder={placeholderText}
                                className="w-full px-3 py-2 rounded-md border border-ink-200 text-sm outline-none focus:border-accent font-mono"
                              />
                            </label>
                          );
                        })}

                        {providerError && (
                          <p className="text-sm text-red-700 bg-red-50 border border-red-100 rounded-md px-3 py-2">{providerError}</p>
                        )}
                      </>
                    );
                  })()}
                </div>

                <div className="px-5 py-4 border-t border-ink-200">
                  <button
                    onClick={() => saveProviderConfig(providerTab)}
                    disabled={providerSaving}
                    className={`w-full h-10 rounded-md text-sm font-semibold text-white disabled:opacity-40 ${
                      providerSaved ? 'bg-accent-mid' : 'bg-accent hover:bg-accent-mid'
                    }`}
                  >
                    {providerSaving ? 'Saving…' : providerSaved ? '✓ Saved' : `Save ${providerTab} credentials`}
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="p-5 space-y-3">
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-ink-500">Current password</span>
                    <input
                      type="password"
                      autoComplete="current-password"
                      value={pwdCurrent}
                      onChange={(e) => setPwdCurrent(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-ink-200 text-sm outline-none focus:border-accent"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-ink-500">New password</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={pwdNew}
                      onChange={(e) => setPwdNew(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-ink-200 text-sm outline-none focus:border-accent"
                    />
                  </label>
                  {pwdMsg && (
                    <p className={`text-sm rounded-md px-3 py-2 border ${
                      pwdMsg.includes('updated') ? 'text-accent bg-accent-soft border-accent/20' : 'text-red-700 bg-red-50 border-red-100'
                    }`}>{pwdMsg}</p>
                  )}
                </div>
                <div className="px-5 py-4 border-t border-ink-200">
                  <button
                    onClick={changePassword}
                    disabled={!pwdCurrent || !pwdNew}
                    className="w-full h-10 rounded-md bg-ink-900 text-white text-sm font-semibold disabled:opacity-40"
                  >
                    Update password
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

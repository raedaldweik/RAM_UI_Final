import { useState, useEffect, useCallback } from 'react';
import SignIn from './SignIn';
import { useLanguage } from '../context/LanguageContext';
import { getHealth, loadSession, saveSession, clearSession, restoreSession, signOut } from '../services/api';

/** App header: SAS logo · title · RAM connection status, sign-in / sign-out, language. */
export default function Header() {
  const { t, toggle } = useLanguage();
  const [health, setHealth] = useState(null);
  const [signingOut, setSigningOut] = useState(false);

  // Health, re-checked every minute and whenever a call comes back "not signed
  // in". If the backend lost this browser's session (a redeploy), the copy the
  // browser kept is handed back before anyone is asked to sign in again.
  const check = useCallback(async () => {
    let h;
    try { h = await getHealth(); } catch { setHealth({ status: 'down' }); return; }
    if (h.status === 'signin_required') {
      const saved = loadSession();
      if (saved) {
        try {
          const r = await restoreSession(saved);
          if (r.ok) { saveSession(r.session); window.location.reload(); return; }
        } catch { clearSession(); }
      }
    }
    setHealth(h);
  }, []);

  useEffect(() => {
    check();
    const timer = setInterval(check, 60000);
    window.addEventListener('ram:signin-required', check);
    return () => { clearInterval(timer); window.removeEventListener('ram:signin-required', check); };
  }, [check]);

  const ok = health?.status === 'ok';
  const needsSignin = health?.status === 'signin_required';
  // Sign out only makes sense for an interactive sign-in (not a configured token or the mock)
  const canSignOut = ok && health?.mode === 'live' && health?.auth === 'device';
  const doSignOut = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try { await signOut(); } catch { /* the local copy is gone either way */ }
    window.location.reload();
  };

  const label = health == null ? t('connecting')
    : health.mode === 'mock' ? t('mockMode')
    : ok ? t('connected')
    : needsSignin ? t('signInRequired')
    : health.status === 'unconfigured' ? t('notConfigured')
    : t('backendOffline');

  // Never leave someone guessing why they are not looking at their own agents.
  const notice = health?.mode === 'mock' ? t('noticeMock')
    : health?.status === 'unconfigured' ? t('noticeUnconfigured')
    : null;

  return (
    <>
    <header className="app-header">
      <img className="brand-logo" src="/sas_logo.png" alt="SAS"
        onError={e => { e.target.style.display = 'none'; }} />

      <div className="title-block">
        <div className="title-row">
          <h1 className="app-title">{t('appTitle')}</h1>
          <div className="accent-line" />
        </div>
      </div>

      <div className="header-controls">
        <div className="status-pill" title={health?.ramUrl && health.mode === 'live' ? health.ramUrl : undefined}>
          <span className={`w-2 h-2 rounded-full ${ok ? '' : 'animate-pulse'}`}
            style={{ background: ok ? 'var(--green)' : needsSignin ? 'var(--amber)' : health ? 'var(--red)' : 'var(--amber)' }} />
          <span>{label}</span>
        </div>
        {needsSignin && <SignIn health={health} />}
        {canSignOut && (
          <button onClick={doSignOut} disabled={signingOut} className="header-btn" title={t('signOutTitle')}>
            {signingOut ? '…' : t('signOut')}
          </button>
        )}
        <button onClick={toggle} className="header-btn" title="English / عربي">{t('langButton')}</button>
      </div>
    </header>
    {notice && (
      <div className="setup-notice" role="status">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="shrink-0 mt-[2px]" aria-hidden="true">
          <circle cx="12" cy="12" r="9" /><line x1="12" y1="8" x2="12" y2="12.5" /><line x1="12" y1="16" x2="12" y2="16.01" />
        </svg>
        <span>{notice}</span>
      </div>
    )}
    </>
  );
}

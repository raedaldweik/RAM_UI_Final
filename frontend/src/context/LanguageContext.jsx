import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { translate } from '../i18n';

const LanguageContext = createContext();

// UI language (English / Arabic), remembered per browser. Sets lang and dir on
// <html> so the whole app, modals included, mirrors for Arabic.
export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem('ram-ui-lang') || 'en'; } catch { return 'en'; }
  });

  useEffect(() => {
    try { localStorage.setItem('ram-ui-lang', lang); } catch { /* private mode */ }
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
    document.title = translate(lang, 'appTitle');
  }, [lang]);

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang]);
  const toggle = useCallback(() => setLang(l => (l === 'ar' ? 'en' : 'ar')), []);

  return (
    <LanguageContext.Provider value={{ lang, setLang, t, toggle, isRTL: lang === 'ar' }}>
      {children}
    </LanguageContext.Provider>
  );
}

export const useLanguage = () => useContext(LanguageContext);

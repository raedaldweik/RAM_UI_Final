// UI strings — English / Arabic. The toggle in the header switches the whole
// app (and flips it to right-to-left). The answers themselves come from the
// RAM agent, which follows the language of the question.

const STR = {
  appTitle: { en: 'SAS Retrieval Agent Assistant', ar: 'مساعد SAS Retrieval Agent' },
  connecting: { en: 'Connecting…', ar: 'جارٍ الاتصال…' },
  connected: { en: 'Connected', ar: 'متصل' },
  mockMode: { en: 'Mock mode', ar: 'وضع المحاكاة' },
  signInRequired: { en: 'Sign in required', ar: 'يلزم تسجيل الدخول' },
  notConfigured: { en: 'Not configured', ar: 'غير مُهيّأ' },
  backendOffline: { en: 'Backend offline', ar: 'الخادم غير متصل' },
  langButton: { en: 'عربي', ar: 'English' },
  // Shown under the header whenever the page is not talking to a real RAM
  noticeMock: {
    en: 'Demo mode: these agents and answers are made up. To connect to your own RAM, set RAM_API_URL to its address (in backend/.env for a local run, in the Variables tab on Railway) and restart.',
    ar: 'وضع العرض التجريبي: هؤلاء الوكلاء والإجابات غير حقيقية. للاتصال ببيئة RAM الخاصة بك، اضبط RAM_API_URL على عنوانها (في backend/.env عند التشغيل المحلي، أو في تبويب Variables على Railway) ثم أعد التشغيل.',
  },
  noticeUnconfigured: {
    en: 'Not connected to a RAM yet. Set RAM_API_URL to your RAM address, for example https://your-host/SASRetrievalAgentManager (in backend/.env for a local run, in the Variables tab on Railway), then restart. For a demo with made-up data, set RAM_MOCK=true instead.',
    ar: 'لم يتم الاتصال ببيئة RAM بعد. اضبط RAM_API_URL على عنوان RAM الخاص بك، مثل https://your-host/SASRetrievalAgentManager (في backend/.env عند التشغيل المحلي، أو في تبويب Variables على Railway) ثم أعد التشغيل. لعرض تجريبي ببيانات غير حقيقية، اضبط RAM_MOCK=true بدلاً من ذلك.',
  },
  you: { en: 'You', ar: 'أنت' },

  // Sign-in (Keycloak device flow / Viya paste-the-code flow)
  signIn: { en: 'Sign in', ar: 'تسجيل الدخول' },
  signOut: { en: 'Sign out', ar: 'تسجيل الخروج' },
  signOutTitle: { en: 'Sign out of RAM on this browser', ar: 'تسجيل الخروج من RAM على هذا المتصفح' },
  signInTitle: { en: 'Sign in to your assistant', ar: 'سجّل الدخول إلى مساعدك' },
  signInSso: { en: 'Authenticate through single sign-on', ar: 'المصادقة عبر تسجيل الدخول الموحّد' },
  signInRam: { en: 'Authenticate with your RAM credentials', ar: 'المصادقة ببيانات اعتماد RAM الخاصة بك' },
  codeInstructions: {
    en: 'A sign-in page just opened in a new tab. Log in there — it will show you an authorization code. Copy it and paste it below.',
    ar: 'فُتحت صفحة تسجيل الدخول في تبويب جديد. سجّل الدخول هناك — ستظهر لك رمز تفويض. انسخه والصقه أدناه.',
  },
  openSignInPage: { en: 'Open sign-in page ↗', ar: 'فتح صفحة تسجيل الدخول ↗' },
  pasteCode: { en: 'Paste authorization code…', ar: 'الصق رمز التفويض…' },
  connect: { en: 'Connect', ar: 'اتصال' },
  deviceInstructions: {
    en: 'Open the verification page, sign in with your RAM credentials, and enter this code:',
    ar: 'افتح صفحة التحقق، وسجّل الدخول ببيانات اعتماد RAM، ثم أدخل هذا الرمز:',
  },
  openVerification: { en: 'Open verification page ↗', ar: 'فتح صفحة التحقق ↗' },
  waitingApproval: { en: 'Waiting for approval…', ar: 'في انتظار الموافقة…' },
  close: { en: 'Close', ar: 'إغلاق' },
  cancel: { en: 'Cancel', ar: 'إلغاء' },

  recentConversations: { en: 'Recent conversations', ar: 'المحادثات الأخيرة' },
  newConversation: { en: '+ New conversation', ar: '+ محادثة جديدة' },
  newConversationTitle: { en: 'New conversation', ar: 'محادثة جديدة' },
  rename: { en: 'Rename', ar: 'إعادة تسمية' },
  delete: { en: 'Delete', ar: 'حذف' },

  welcome: {
    en: 'Welcome to the SAS Retrieval Agent Assistant. Pick an agent (or a collection) from the dropdown above and ask anything. Every answer shows its sources, tool calls and retrieval trace.',
    ar: 'مرحباً بك في مساعد SAS Retrieval Agent. اختر وكيلاً (أو مجموعة) من القائمة أعلاه واسأل ما تشاء. كل إجابة تعرض مصادرها واستدعاءات أدواتها وأثر الاسترجاع.',
  },

  selectAgent: { en: 'Select an agent', ar: 'اختر وكيلاً' },
  serviceUnreachable: { en: 'Service unreachable', ar: 'تعذّر الوصول إلى الخدمة' },
  agents: { en: 'Agents', ar: 'الوكلاء' },
  collections: { en: 'Collections', ar: 'المجموعات' },
  noAgents: { en: 'No agents or collections published on this RAM environment.', ar: 'لا يوجد وكلاء أو مجموعات منشورة في بيئة RAM هذه.' },

  selectAgentFirst: { en: 'Select an agent from the dropdown first.', ar: 'اختر وكيلاً من القائمة أولاً.' },
  askAnything: { en: 'Ask {name} anything…', ar: 'اسأل {name} أي شيء…' },
  selectThenAsk: { en: 'Select an agent above, then ask anything…', ar: 'اختر وكيلاً من الأعلى ثم اسأل أي شيء…' },
  attachTooltip: {
    en: 'Attach a document (PDF, DOCX, TXT, CSV…) — its text is sent with your question',
    ar: 'أرفق مستنداً (PDF، DOCX، TXT، CSV…) — يُرسل نصه مع سؤالك',
  },
  speakTooltip: { en: 'Speak instead of typing', ar: 'تحدّث بدلاً من الكتابة' },
  readingDocument: { en: 'Reading document…', ar: 'جارٍ قراءة المستند…' },
  sentWithNext: { en: '· sent with your next question', ar: '· يُرسل مع سؤالك التالي' },
  firstKChars: { en: 'first {n}k chars', ar: 'أول {n} ألف حرف' },
  kChars: { en: '{n}k chars', ar: '{n} ألف حرف' },
  stepsSoFar: { en: '{n} step{s} so far', ar: '{n} خطوة حتى الآن' },
  agentTimeout: {
    en: 'The agent did not answer within {n}s — the query may still be running on the server.',
    ar: 'لم يُجب الوكيل خلال {n} ثانية — قد يكون الاستعلام لا يزال قيد التنفيذ على الخادم.',
  },
  agentErrorPrefix: { en: 'Agent error:', ar: 'خطأ من الوكيل:' },
  errorPrefix: { en: 'Error:', ar: 'خطأ:' },

  toolCallsHeader: { en: 'Agent tool calls · {n} step{s}', ar: 'استدعاءات أدوات الوكيل · {n} خطوة' },

  openInVA: { en: 'Open in SAS Visual Analytics ↗', ar: 'فتح في SAS Visual Analytics ↗' },
  clickToZoom: { en: 'Click to enlarge', ar: 'انقر للتكبير' },

  mapNeedsKey: { en: 'Map ready. Set VITE_TOMTOM_API_KEY to render it (see the README).', ar: 'الخريطة جاهزة. اضبط VITE_TOMTOM_API_KEY لعرضها (راجع ملف README).' },
  loadingMap: { en: 'Loading map…', ar: 'جارٍ تحميل الخريطة…' },
  viewPassage: { en: 'Click to view the retrieved passage', ar: 'انقر لعرض المقطع المسترجَع' },
  detailsTooltip: { en: 'Details: tools, LLM calls, retrieval trace', ar: 'التفاصيل: الأدوات واستدعاءات النموذج وأثر الاسترجاع' },
  emptyAnswer: { en: '(empty answer)', ar: '(إجابة فارغة)' },
  send: { en: 'Send', ar: 'إرسال' },

  queryDetails: { en: 'Query details', ar: 'تفاصيل الاستعلام' },
  loadingTrace: { en: 'loading trace…', ar: 'جارٍ تحميل الأثر…' },
  inputPrompt: { en: 'Input prompt', ar: 'نص السؤال' },
  toolCallsSection: { en: 'Tool calls', ar: 'استدعاءات الأدوات' },
  noToolCalls: { en: 'No tool calls recorded for this query.', ar: 'لا توجد استدعاءات أدوات مسجّلة لهذا الاستعلام.' },
  retrievalSection: { en: 'Retrieval calls (RAG)', ar: 'استدعاءات الاسترجاع (RAG)' },
  noRetrieval: { en: 'No retrieval calls recorded for this query.', ar: 'لا توجد استدعاءات استرجاع مسجّلة لهذا الاستعلام.' },
  llmSection: { en: 'LLM calls', ar: 'استدعاءات النموذج اللغوي' },
  noLlm: { en: 'No LLM calls recorded for this query.', ar: 'لا توجد استدعاءات نموذج لغوي مسجّلة لهذا الاستعلام.' },
  contextSection: { en: 'Retrieved context', ar: 'السياق المسترجَع' },
  noContext: { en: 'No context passages attached to this answer.', ar: 'لا توجد مقاطع سياق مرفقة بهذه الإجابة.' },
  inputLabel: { en: 'Input', ar: 'المدخلات' },
  outputLabel: { en: 'Output', ar: 'المخرجات' },
  promptLabel: { en: 'Prompt', ar: 'الموجّه' },
  responseLabel: { en: 'Response', ar: 'الاستجابة' },
  open: { en: 'open ↗', ar: 'فتح ↗' },
  tokens: { en: 'tokens', ar: 'رمز' },
  promptCompletion: { en: '{p} prompt · {c} completion', ar: '{p} إدخال · {c} إخراج' },
};


export function translate(lang, key, vars) {
  const entry = STR[key];
  let s = (entry && (entry[lang] ?? entry.en)) ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  }
  return s;
}

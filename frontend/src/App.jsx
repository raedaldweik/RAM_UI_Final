import { LanguageProvider } from './context/LanguageContext';
import { ChatProvider } from './context/ChatContext';
import Header from './components/Header';
import ChatPage from './pages/ChatPage';

// Atmospheric bokeh backdrop: [tone, position/size class]
const BOKEH = [
  ['mega-teal', 'a1'], ['mega-cyan', 'a2'], ['mega-purple', 'a3'], ['mega-amber', 'a4'],
  ['mega-cyan mega-teal-2', 'a5'],
  ['teal-blob', 'm1'], ['cyan-blob', 'm2'], ['teal-blob', 'm3'], ['cyan-blob', 'm4'], ['teal-blob', 'm5'],
  ['purple-blob', 'm6'], ['teal-blob', 'm7'], ['amber-blob', 'm8'], ['cyan-blob', 'm9'], ['teal-blob', 'm10'],
  ['amber-blob', 'm11'], ['teal-blob', 'm12'], ['purple-blob', 'm13'], ['cyan-blob', 'm14'], ['teal-blob', 'm15'],
];

export default function App() {
  return (
    <LanguageProvider>
      <ChatProvider>
        <div className="app-shell">
          <div className="bokeh-layer" aria-hidden="true">
            {BOKEH.map(([tone, spot]) => <div key={spot} className={`bokeh-dot ${tone} ${spot}`} />)}
          </div>

          <Header />
          <div className="flex-1 min-h-0 relative z-[1]">
            <ChatPage />
          </div>
        </div>
      </ChatProvider>
    </LanguageProvider>
  );
}

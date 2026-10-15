/**
 * Точка входа интерфейса реестра научных проектов.
 *
 * Токен сессии хранится в localStorage и передаётся в заголовке Authorization,
 * а не в cookie: bearer-токен не подвержен подделке межсайтовых запросов
 * (SEC-04), поэтому отдельный CSRF-токен не нужен.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './auth';
import { installDemoMode } from './demo/mock';
import { installErrorCollector } from './errors';
import './styles.css';
import './report.css';

// Только при сборке с VITE_DEMO=1. В обычной сборке подмены запросов нет.
installDemoMode();

// Подписка на ошибки браузера. Стоит до отрисовки, чтобы не потерять
// ошибку, случившуюся во время первого рендера.
installErrorCollector();

const container = document.getElementById('root');
if (!container) throw new Error('Не найден элемент #root в index.html');

// База сборки нужна и роутеру. На GitHub Pages сайт лежит в подкаталоге
// (/reestr-demo/), и без basename ссылка вида /projects уводила бы за его
// пределы: внутри вкладки всё работало, но перезагрузка отдавала бы 404 —
// проверить сохранность правок было бы невозможно.
const buildBase = import.meta.env.BASE_URL;
const basename = buildBase.startsWith('/') ? buildBase : undefined;

createRoot(container).render(
  <StrictMode>
    <BrowserRouter basename={basename}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
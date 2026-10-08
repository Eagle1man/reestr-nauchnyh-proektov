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
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('Не найден элемент #root в index.html');

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
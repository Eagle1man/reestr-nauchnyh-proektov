/**
 * Полоса режима демонстрации: объясняет, где хранятся данные, и даёт три
 * действия — выгрузить, загрузить, вернуть исходный снимок.
 *
 * Показывается только в сборке с VITE_DEMO=1 (в обычной сборке возвращает
 * null), поэтому на рабочей версии её нет.
 *
 * ЗАЧЕМ ВЫГРУЗКА. Правки живут в браузере тестировщика, и заказчик не увидит
 * их иначе. Файл выгрузки — единственный способ показать результат: сам
 * он наружу не уходит, отдаёт его только человек (SEC-05).
 *
 * Откат выполняется перезагрузкой страницы: состояние демонстрации живёт
 * в модуле, и без перезагрузки открытые экраны продолжили бы показывать
 * старые данные, хотя хранилище уже очищено.
 */
import { useRef, useState, type ChangeEvent } from 'react';
import {
  exportDemoData, importDemoData, isDemoMode, resetDemoData,
} from './mock';
import './demo.css';

/** 2 МБ: настоящая выгрузка сейчас около 35 КБ, больше — не наш файл. */
const MAX_FILE_BYTES = 2_000_000;

export default function DemoBar() {
  const [armed, setArmed] = useState(false);
  const [message, setMessage] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  if (!isDemoMode()) return null;

  function handleReset() {
    if (!armed) {
      setArmed(true);
      return;
    }
    resetDemoData();
    window.location.reload();
  }

  function handleExport() {
    const name = exportDemoData();
    setMessage(`Файл ${name} сохранён — его можно прислать.`);
  }

  async function handleImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';   // иначе тот же файл второй раз не выбрать
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setMessage('Файл слишком большой: ожидалась выгрузка состояния демо.');
      return;
    }
    let text = '';
    try {
      text = await file.text();
    } catch {
      setMessage('Файл не удалось прочитать.');
      return;
    }
    if (!importDemoData(text)) {
      setMessage('Это не выгрузка состояния демо — данные не заменены.');
      return;
    }
    // Перезагрузка, чтобы открытые экраны читали уже новое состояние.
    window.location.reload();
  }

  return (
    <div className="demo-bar" role="note">
      <span className="demo-bar__text">
        Демо-режим: правки хранятся в вашем браузере и переживают перезагрузку.
        {message && <span className="demo-bar__status"> {message}</span>}
      </span>

      <button type="button" className="demo-bar__action" onClick={handleExport}>
        Выгрузить
      </button>

      <button
        type="button"
        className="demo-bar__action"
        onClick={() => fileInput.current?.click()}
      >
        Загрузить
      </button>

      <input
        ref={fileInput}
        type="file"
        accept="application/json,.json"
        className="demo-bar__file"
        onChange={(event) => void handleImport(event)}
      />

      <button
        type="button"
        className={`demo-bar__reset${armed ? ' demo-bar__reset--armed' : ''}`}
        onClick={handleReset}
        onBlur={() => setArmed(false)}
      >
        {armed ? 'Точно вернуть?' : 'Вернуть демо-данные'}
      </button>
    </div>
  );
}

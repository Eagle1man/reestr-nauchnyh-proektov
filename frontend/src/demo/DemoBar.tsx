/**
 * Полоса режима демонстрации: объясняет, где хранятся данные, и умеет
 * вернуть исходный снимок.
 *
 * Полоса показывается только в сборке с VITE_DEMO=1 (в обычной сборке
 * возвращает null), поэтому на рабочей версии её нет.
 *
 * Сброс выполняется перезагрузкой страницы: состояние демонстрации живёт
 * в модуле, и без перезагрузки открытые экраны продолжили бы показывать
 * старые данные, хотя хранилище уже очищено.
 */
import { useState } from 'react';
import { isDemoMode, resetDemoData } from './mock';
import './demo.css';

export default function DemoBar() {
  const [armed, setArmed] = useState(false);

  if (!isDemoMode()) return null;

  function handleReset() {
    if (!armed) {
      setArmed(true);
      return;
    }
    resetDemoData();
    window.location.reload();
  }

  return (
    <div className="demo-bar" role="note">
      <span className="demo-bar__text">
        Демо-режим: изменённые данные сохраняются в вашем браузере и
        остаются после перезагрузки.
      </span>
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

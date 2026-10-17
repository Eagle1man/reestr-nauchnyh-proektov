/**
 * Полоса режима демонстрации: объясняет, где хранятся данные, и даёт четыре
 * действия — выгрузить, загрузить, вернуть исходный снимок, посмотреть
 * структуру вуза.
 *
 * Показывается только в сборке с VITE_DEMO=1 (в обычной сборке возвращает
 * null), поэтому на рабочей версии её нет.
 *
 * ЗАЧЕМ ВЫГРУЗКА. Правки живут в браузере тестировщика, и заказчик не увидит
 * их иначе. Файл выгрузки — единственный способ показать результат: сам
 * он наружу не уходит, отдаёт его только человек (SEC-05).
 *
 * ЗАЧЕМ СТРУКТУРА. Демонстрация показывает интерфейс на пилотном снимке, и
 * раньше подразделения вуза в нём были выдуманными («Южный университет
 * (ИУБиП)» у всех). Теперь это настоящая разбивка из оргструктуры, и
 * тестировщик видит, с какими подразделениями он работает.
 *
 * Откат и загрузка выполняются перезагрузкой страницы: состояние демонстрации
 * живёт в модуле, и без перезагрузки открытые экраны продолжили бы показывать
 * старые данные, хотя хранилище уже заменено.
 */
import { useRef, useState, type ChangeEvent } from 'react';
import {
  currentDemoRole, DEMO_ROLES, exportDemoData, importDemoData, isDemoMode,
  resetDemoData, setDemoRole,
} from './mock';
import './demo.css';

/** 2 МБ: настоящая выгрузка сейчас около 35 КБ, больше — не наш файл. */
const MAX_FILE_BYTES = 2_000_000;

interface Unit {
  code: string;
  title: string;
  kind: string;
  parent: string | null;
  relation?: string;
  includes?: string[];
}

interface Departments {
  university: string;
  academic_year: string;
  source: string;
  site_note: string;
  units: Unit[];
  schools: { title: string; place: string }[];
  aspirantura: { code: string; title: string; form: string }[];
}

const KIND_LABELS: Record<string, string> = {
  управление: 'управление',
  'коллегиальный орган': 'коллегиальный орган',
  дирекция: 'академическая дирекция',
  колледж: 'колледж',
};

function UnitBranch({ unit, units }: { unit: Unit; units: Unit[] }) {
  const children = units.filter((item) => item.parent === unit.code);
  return (
    <li>
      <span>{unit.title}</span>
      {unit.includes?.length ? (
        <span className="demo-units__note"> — в составе: {unit.includes.join(', ')}</span>
      ) : null}
      {children.length > 0 && (
        <ul>
          {children.map((child) => (
            <UnitBranch key={child.code} unit={child} units={units} />
          ))}
        </ul>
      )}
    </li>
  );
}

function UnitGroup({ title, units, items }: {
  title: string; units: Unit[]; items: Unit[];
}) {
  if (items.length === 0) return null;
  return (
    <details>
      <summary>{title} ({items.length})</summary>
      <ul>
        {items.map((item) => <UnitBranch key={item.code} unit={item} units={units} />)}
      </ul>
    </details>
  );
}

function DepartmentsPanel({ data, onClose }: {
  data: Departments; onClose: () => void;
}) {
  // Цепочка вершины: корнем дерева теперь «Ректорат» — так он назван
// в официальной таблице структурных подразделений.
  const chain = ['rectorat', 'rector_office']
    .map((code) => data.units.find((unit) => unit.code === code))
    .filter((unit): unit is Unit => Boolean(unit));
  const collegial = data.units.filter((unit) => unit.kind === 'коллегиальный орган');
  // Академии именно блока ректора: «Академия профессионального образования»
  // тоже академия по виду, но подчинена директору по маркетингу и в этом
  // перечне была бы лишней.
  const academies = data.units.filter((unit) => unit.kind === 'академия'
    && unit.parent === 'rectorat');
  const chairs = data.units.filter((unit) => unit.kind === 'кафедра');
  const blocks = data.units.filter((unit) => unit.parent === 'rectorat'
    && !['кафедра', 'академия', 'коллегиальный орган', 'подразделение']
      .includes(unit.kind));

  return (
    <div className="demo-units" role="dialog" aria-label="Структура вуза">
      <div className="demo-units__head">
        <span className="demo-units__title">
          {data.university}: структура подразделений, {data.academic_year}
        </span>
        <button type="button" className="demo-units__close" onClick={onClose}>Свернуть</button>
      </div>
      <div className="demo-units__source">Источник: {data.source}. {data.site_note}</div>

      <ul className="demo-units__chain">
        {chain.map((unit) => (
          <li key={unit.code}>
            {unit.title}
            {KIND_LABELS[unit.kind] ? (
              <span className="demo-units__note"> ({KIND_LABELS[unit.kind]})</span>
            ) : null}
          </li>
        ))}
      </ul>

      {collegial.length > 0 && (
        <div className="demo-units__collegial">
          Коллегиальные органы (связь с ректором пунктирная):
          {collegial.map((unit) => unit.title).join(' · ')}
        </div>
      )}

      <UnitGroup title="Блоки, подчинённые ректору" units={data.units} items={blocks} />
      <UnitGroup title="Академии" units={data.units} items={academies} />
      <UnitGroup title="Кафедры" units={data.units} items={chairs} />

      {data.schools.length > 0 && (
        <details>
          <summary>Научные школы ({data.schools.length})</summary>
          <ul>
            {data.schools.map((school) => (
              <li key={school.title}>
                {school.title}
                <span className="demo-units__note"> — {school.place}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {data.aspirantura.length > 0 && (
        <details>
          <summary>Направления подготовки в аспирантуре ({data.aspirantura.length})</summary>
          <ul>
            {data.aspirantura.map((item) => (
              <li key={item.code}>
                <span className="demo-units__code">{item.code}</span> {item.title}
                <span className="demo-units__note"> — {item.form}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function DemoBar() {
  const [armed, setArmed] = useState(false);
  const [message, setMessage] = useState('');
  const [units, setUnits] = useState<Departments | null>(null);
  const [unitsFailed, setUnitsFailed] = useState(false);
  const [showUnits, setShowUnits] = useState(false);
  const [role] = useState(currentDemoRole());
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

  async function toggleUnits() {
    if (showUnits) {
      setShowUnits(false);
      return;
    }
    setShowUnits(true);
    if (units || unitsFailed) return;   // грузим один раз за сеанс
    try {
      const response = await fetch('/api/departments');
      setUnits(await response.json() as Departments);
    } catch {
      setUnitsFailed(true);
    }
  }

  return (
    <>
      {showUnits && (units || unitsFailed) && (
        <DepartmentsPanel
          data={units ?? {
            university: '', academic_year: '', source: '', site_note: '',
            units: [], schools: [], aspirantura: [],
          }}
          onClose={() => setShowUnits(false)}
        />
      )}
      {showUnits && unitsFailed && (
        <div className="demo-units demo-units--failed">
          Структура вуза не загрузилась: снимок не содержит /api/departments.
        </div>
      )}

      <div className="demo-bar" role="note">
        <span className="demo-bar__text">
          Демо-режим: правки хранятся в вашем браузере и переживают перезагрузку.
          {message && <span className="demo-bar__status"> {message}</span>}
          {/* Подпись про лица видна на каждой странице: в демо они вымышленные,
              и без этой оговорки их можно принять за настоящих сотрудников.
              Реальные данные — только в разделе «Научная деятельность». */}
          <span className="demo-bar__note">
            {' '}Лица в демо вымышленные; реальные данные — только в разделе
            «Научная деятельность» (выгрузка eLIBRARY/РИНЦ и Scopus).
          </span>
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
          className={`demo-bar__action${showUnits ? ' demo-bar__action--on' : ''}`}
          onClick={() => void toggleUnits()}
        >
          Структура вуза
        </button>

        {/* Роль переключается без входа: за ней нет настоящей учётной записи,
            это демонстрация синтетических данных. Права проверяются так же,
            как на сервере, поэтому закрытые разделы остаются закрытыми для
            тех ролей, которым они не положены. */}
        <label className="demo-bar__role">
          Роль:
          <select
            value={role.code}
            onChange={(event) => {
              setDemoRole(event.target.value);
              window.location.reload();
            }}
          >
            {DEMO_ROLES.map((item) => (
              <option key={item.code} value={item.code}>{item.title}</option>
            ))}
          </select>
        </label>

        <button
          type="button"
          className={`demo-bar__reset${armed ? ' demo-bar__reset--armed' : ''}`}
          onClick={handleReset}
          onBlur={() => setArmed(false)}
        >
          {armed ? 'Точно вернуть?' : 'Вернуть демо-данные'}
        </button>
      </div>
    </>
  );
}
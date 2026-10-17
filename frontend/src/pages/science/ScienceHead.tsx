/**
 * Каркас раздела «Научная деятельность»: заголовок, переходы между
 * частями раздела и честная пометка о происхождении данных.
 *
 * Пометка показывается только когда её прислал сервер: в боевой версии раздела
 * её быть не должно (там данные настоящие), а в демо она обязана быть, иначе
 * демонстрационные записи выглядели бы настоящей выгрузкой eLIBRARY/РИНЦ,
 * что ТЗ прямо запрещает.
 */
import { NavLink } from 'react-router-dom';
import { Alert } from '../../components/ui';

const TABS = [
  { to: '/science', label: 'Публикации', key: 'publications', end: true },
  { to: '/science/venues', label: 'Издания', key: 'venues', end: false },
  { to: '/science/participants', label: 'Участники', key: 'participants', end: false },
  { to: '/science/topic', label: 'Тема и оценка', key: 'topic', end: false },
] as const;

export type ScienceTab = (typeof TABS)[number]['key'];

export function ScienceHead({ notice, description }: {
  active: ScienceTab;
  notice?: string;
  description: string;
}) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Научная деятельность</h1>
          <p>{description}</p>
        </div>
      </div>
      <nav className="tabs" aria-label="Разделы научной деятельности">
        {TABS.map((tab) => (
          <NavLink
            key={tab.key}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => (isActive ? 'tabs__item tabs__item--on' : 'tabs__item')}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      {notice && (
        <Alert kind="warn">
          <strong>Демонстрационные данные.</strong> {notice}
        </Alert>
      )}
    </>
  );
}

/** Число и подпись: показатель всегда виден рядом со своим знаменателем. */
export function Metric({ value, label }: { value: number | string; label: string }) {
  return (
    <div className="stat">
      <div className="stat__value">{value}</div>
      <div className="stat__label">{label}</div>
    </div>
  );
}
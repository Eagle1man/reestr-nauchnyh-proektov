import { NavLink, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth';
import ErrorReportButton from './components/ErrorReportButton';
import DemoBar from './demo/DemoBar';
import { ErrorAlert } from './components/ui';
import AdminPage from './pages/Admin';
import DashboardPage from './pages/Dashboard';
import ImportExportPage from './pages/ImportExport';
import LoginPage from './pages/Login';
import NewProjectPage from './pages/NewProject';
import ProfilePage from './pages/Profile';
import ProjectDetailPage from './pages/ProjectDetail';
import ProjectsPage from './pages/Projects';
import PublicPage from './pages/Public';
import RemindersPage from './pages/Reminders';
import { ScienceParticipantPage, ScienceParticipantsPage } from './pages/science/ScienceParticipants';
import SciencePublicationPage from './pages/science/SciencePublication';
import SciencePublicationsPage from './pages/science/SciencePublications';
import ScienceTopicPage from './pages/science/ScienceTopic';
import { ScienceVenuePage, ScienceVenuesPage } from './pages/science/ScienceVenues';

/** Закрытая рабочая зона: требуется вход (п.3.1 ТЗ). */
function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ padding: 40 }}>Проверка учётной записи…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}

/** Раздел доступен только администратору; иначе — точное объяснение (FR-02). */
function AdminOnly() {
  const { can } = useAuth();
  if (!can('is_admin')) {
    return (
      <ErrorAlert error={new Error('Раздел доступен техническому администратору')} />
    );
  }
  return <Outlet />;
}

/** Импорт и выгрузка — только для ролей, которым это нужно (FR-29, FR-28). */
function TransferOnly() {
  const { can } = useAuth();
  if (!can('can_import') && !can('is_portfolio')) {
    return (
      <ErrorAlert
        error={new Error('Импорт и выгрузка доступны секретарю, проректору и администратору')}
      />
    );
  }
  return <Outlet />;
}

function LoginGate() {
  const { user, loading } = useAuth();
  if (loading) return <div style={{ padding: 40 }}>Проверка учётной записи…</div>;
  if (user) return <Navigate to="/" replace />;
  return <LoginPage />;
}

/** Каркас закрытой зоны: шапка с навигацией и именем пользователя. */
function Shell() {
  const { user } = useAuth();
  return (
    <div className="app">
      <header className="topbar">
        <p className="topbar__title">
          Реестр научных проектов
          <small>Южный университет (ИУБиП)</small>
        </p>
        <nav className="topbar__nav" aria-label="Основная навигация">
          <NavLink to="/" end>Панель</NavLink>
          <NavLink to="/projects">Проекты</NavLink>
          <NavLink to="/reminders">Назначения</NavLink>
          {/* Раздел «Научная деятельность» по отдельному ТЗ мониторинга. В
              боевой версии он появится вместе с API раздела; пока API отвечает
              только в демонстрации, пункт меню показывается в той же сборке, что
              и сама демонстрация, — иначе пользователь попал бы в пустую
              страницу. */}
          {import.meta.env.VITE_DEMO === '1' && (
            <NavLink to="/science">Научная деятельность</NavLink>
          )}
          <NavLink to="/transfer">Импорт и выгрузка</NavLink>
          <NavLink to="/admin">Администрирование</NavLink>
        </nav>
        <div className="topbar__user">
          <NavLink to="/profile" title={user?.full_name}>{user?.full_name}</NavLink>
          <a href="/public" target="_blank" rel="noreferrer">Открытый раздел</a>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <>
      <Routes>
      {/* Открытая витрина раздела «Наука» — без входа (п.9.1) */}
      <Route path="/public" element={<PublicPage />} />

      <Route path="/login" element={<LoginGate />} />

      {/* Закрытая рабочая зона */}
      <Route element={<Protected />}>
        <Route element={<Shell />}>
          <Route index element={<DashboardPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/new" element={<NewProjectPage />} />
          <Route path="projects/:id" element={<ProjectDetailPage />} />
          <Route path="reminders" element={<RemindersPage />} />
          <Route path="science" element={<SciencePublicationsPage />} />
          <Route path="science/publications/:id" element={<SciencePublicationPage />} />
          <Route path="science/venues" element={<ScienceVenuesPage />} />
          <Route path="science/venues/:id" element={<ScienceVenuePage />} />
          <Route path="science/participants" element={<ScienceParticipantsPage />} />
          <Route path="science/participants/:id" element={<ScienceParticipantPage />} />
          <Route path="science/topic" element={<ScienceTopicPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route element={<TransferOnly />}>
            <Route path="transfer" element={<ImportExportPage />} />
          </Route>
          <Route element={<AdminOnly />}>
            <Route path="admin" element={<AdminPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Кнопка отчёта доступна на любой странице, включая экран входа:
          именно там человек чаще всего видит непонятную ошибку. */}
      <ErrorReportButton />
      {/* Полоса только в сборке с VITE_DEMO=1: условие проверяется на этапе
          сборки, поэтому в обычную версию этот интерфейс не попадает. */}
      {import.meta.env.VITE_DEMO === '1' && <DemoBar />}
    </>
  );
}
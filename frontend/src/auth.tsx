import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from 'react';
import { auth, getToken, Matrix, Person, setToken, User } from './api';
import { Spinner } from './components/ui';

interface AuthState {
  user: User | null;
  matrix: Matrix | null;
  person: Person | null;
  loading: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
  can: (key: keyof Matrix) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(Ctx);
  if (!value) throw new Error('useAuth вызван вне AuthProvider');
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [person, setPerson] = useState<Person | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setMatrix(null);
      setLoading(false);
      return;
    }
    try {
      const data = await auth.me();
      setUser(data.user);
      setMatrix(data.matrix);
      setPerson(data.person);
    } catch {
      // Сессия истекла или отозвана: интерфейс возвращается на форму входа.
      setToken(null);
      setUser(null);
      setMatrix(null);
      setPerson(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (loginValue: string, password: string) => {
    const data = await auth.login(loginValue, password);
    setToken(data.token);
    const me = await auth.me();
    setUser(me.user);
    setMatrix(me.matrix);
    setPerson(me.person);
    setLoading(false);
  }, []);

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } finally {
      setToken(null);
      setUser(null);
      setMatrix(null);
      setPerson(null);
    }
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => Boolean(matrix?.global_roles.some((r) => roles.includes(r))),
    [matrix],
  );

  const can = useCallback(
    (key: keyof Matrix) => Boolean(matrix?.[key]),
    [matrix],
  );

  if (loading) {
    return (
      <div style={{ padding: 40 }}>
        <Spinner text="Проверка учётной записи…" />
      </div>
    );
  }

  return (
    <Ctx.Provider value={{ user, matrix, person, loading, login, logout, refresh, hasRole, can }}>
      {children}
    </Ctx.Provider>
  );
}
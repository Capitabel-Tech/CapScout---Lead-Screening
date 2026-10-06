import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, post, type Staff } from './api'

type AuthState = {
  staff: Staff | null
  loading: boolean
  login: (employeeCode: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [staff, setStaff] = useState<Staff | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api<Staff>('/me')
      .then(setStaff)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) console.error(e)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (employeeCode: string, password: string) => {
    setStaff(await post<Staff>('/auth/login', { employee_code: employeeCode, password }))
  }, [])

  const logout = useCallback(async () => {
    await post('/auth/logout').catch(() => undefined)
    setStaff(null)
  }, [])

  return <AuthContext.Provider value={{ staff, loading, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

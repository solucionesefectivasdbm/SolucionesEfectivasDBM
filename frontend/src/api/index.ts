import { api } from './axios'
import type {
  TokenResponse, Usuario, Gestor, Receptor, CuentaBancaria,
  Cliente, Credito, Pago, RegistrarPagoResponse, Reporte,
  AlertasVencidos, PaginatedResponse,
} from '@/types'

// ─── Auth ─────────────────────────────────────────────────────────────────────
export const authApi = {
  login: (username: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { username, password }),
  logout: () => api.post('/auth/logout'),
}

// ─── Usuarios ─────────────────────────────────────────────────────────────────
export const usuariosApi = {
  listar: (params?: { page?: number; busqueda?: string }) =>
    api.get<PaginatedResponse<Usuario>>('/usuarios', { params }),
  crear: (data: object) => api.post<Usuario>('/usuarios', data),
  obtener: (id: string) => api.get<Usuario>(`/usuarios/${id}`),
  actualizar: (id: string, data: object) => api.patch<Usuario>(`/usuarios/${id}`, data),
  eliminar: (id: string) => api.delete(`/usuarios/${id}`),
  restablecerPassword: (id: string, password_nuevo: string) =>
    api.post(`/usuarios/${id}/restablecer-password`, { password_nuevo }),
  cambiarMiPassword: (password_actual: string, password_nuevo: string) =>
    api.post('/usuarios/me/cambiar-password', { password_actual, password_nuevo }),
}

// ─── Gestores ─────────────────────────────────────────────────────────────────
export const gestoresApi = {
  listar: (params?: { page?: number; busqueda?: string }) =>
    api.get<PaginatedResponse<Gestor>>('/gestores', { params }),
  crear: (data: object) => api.post<Gestor>('/gestores', data),
  obtener: (id: string) => api.get<Gestor>(`/gestores/${id}`),
  actualizar: (id: string, data: object) => api.patch<Gestor>(`/gestores/${id}`, data),
  miPerfil: () => api.get<Gestor>('/gestores/me'),
}

// ─── Receptores ───────────────────────────────────────────────────────────────
export const receptoresApi = {
  listar: (params?: { page?: number; busqueda?: string }) =>
    api.get<PaginatedResponse<Receptor>>('/receptores', { params }),
  crear: (data: object) => api.post<Receptor>('/receptores', data),
  obtener: (id: string) => api.get<Receptor>(`/receptores/${id}`),
  actualizar: (id: string, data: object) => api.patch<Receptor>(`/receptores/${id}`, data),
  eliminar: (id: string) => api.delete(`/receptores/${id}`),
  agregarCuenta: (receptorId: string, data: object) =>
    api.post<CuentaBancaria>(`/receptores/${receptorId}/cuentas`, data),
  actualizarCuenta: (receptorId: string, cuentaId: string, data: object) =>
    api.patch<CuentaBancaria>(`/receptores/${receptorId}/cuentas/${cuentaId}`, data),
}

// ─── Clientes ─────────────────────────────────────────────────────────────────
export const clientesApi = {
  listar: (params?: { page?: number; busqueda?: string; gestor_id?: string; al_dia?: boolean }) =>
    api.get<PaginatedResponse<Cliente>>('/clientes', { params }),
  crear: (data: object) => api.post<Cliente>('/clientes', data),
  obtener: (id: string) => api.get<Cliente>(`/clientes/${id}`),
  actualizar: (id: string, data: object) => api.patch<Cliente>(`/clientes/${id}`, data),
  eliminar: (id: string) => api.delete(`/clientes/${id}`),
}

// ─── Créditos ─────────────────────────────────────────────────────────────────
export const creditosApi = {
  listar: (params?: { page?: number; busqueda?: string; solo_activos?: boolean; cliente_id?: string; gestor_id?: string }) =>
    api.get<PaginatedResponse<Credito>>('/creditos', { params }),
  resumenCartera: () => api.get<{ saldo_capital: number; saldo_intereses: number; saldo_total: number }>('/creditos/resumen-cartera'),
  crear: (data: object) => api.post<Credito>('/creditos', data),
  obtener: (id: string) => api.get<Credito>(`/creditos/${id}`),
  actualizar: (id: string, data: object) => api.patch<Credito>(`/creditos/${id}`, data),
  actualizarDiasPago: (id: string, data: { anchor_dia_1: number; anchor_dia_2?: number }) =>
    api.patch<Credito>(`/creditos/${id}/dias-pago`, data),
  eliminar: (id: string) => api.delete(`/creditos/${id}`),
  historialCuotas: (id: string) => api.get<Pago[]>(`/creditos/${id}/cuotas`),
}

// ─── Pagos ────────────────────────────────────────────────────────────────────
export const pagosApi = {
  listar: (params: {
    anio: number; mes: number; momento?: string;
    sort_dir?: 'asc' | 'desc';
    gestor_id?: string; cliente_id?: string; receptor_id?: string;
    solo_periodicidad?: string; excluir_periodicidad?: string;
    excluir_periodicidades?: string[];
    busqueda?: string; page?: number
  }) => api.get<PaginatedResponse<Pago>>('/pagos', {
    params,
    // FastAPI list[Periodicidad] requires repeated keys (excluir_periodicidades=a&excluir_periodicidades=b).
    // Axios default serialization emits brackets (key[]=a) which FastAPI does not bind.
    // indexes: null forces repeated-key serialization without brackets, per-request only.
    paramsSerializer: { indexes: null },
  }),

  registrar: (pagoId: string, data: { capital_pagado: number; interes_pagado: number }) =>
    api.post<RegistrarPagoResponse>(`/pagos/${pagoId}/registrar`, data),

  confirmarExcedente: (
    pagoId: string,
    montos: { capital_pagado: number; interes_pagado: number },
    destino_excedente: string
  ) => api.post<RegistrarPagoResponse>(`/pagos/${pagoId}/confirmar-excedente`, {
    capital_pagado: montos.capital_pagado,
    interes_pagado: montos.interes_pagado,
    destino_excedente,
  }),

  validar: (pagoId: string, tipo_validacion?: 'completo' | 'incompleto' | 'con_excedente') =>
    api.post<Pago>(`/pagos/${pagoId}/validar`, tipo_validacion ? { tipo_validacion } : {}),

  desvalidar: (pagoId: string) =>
    api.post<Pago>(`/pagos/${pagoId}/desvalidar`),

  modificarFecha: (pagoId: string, fecha_maxima: string) =>
    api.patch<Pago>(`/pagos/${pagoId}/fecha`, { fecha_maxima }),

  modificarReceptor: (pagoId: string, receptor_id: string) =>
    api.patch<Pago>(`/pagos/${pagoId}/receptor`, { receptor_id }),

  noProgramado: (creditoId: string, data: object) =>
    api.post<Pago>(`/pagos/no-programado/${creditoId}`, data),

  alertasProximosVencer: () =>
    api.get<Pago[]>('/pagos/alertas/proximos-vencer'),

  alertasVencidos: () =>
    api.get<AlertasVencidos>('/pagos/alertas/vencidos'),
}

// ─── Reportes ─────────────────────────────────────────────────────────────────
export const reportesApi = {
  generar: (params: { anio: number; mes: number; momento: string }) =>
    api.get<Reporte>('/reportes', { params }),
}

// ─── Auditoría ────────────────────────────────────────────────────────────────
export const auditoriaApi = {
  listar: (params?: {
    entidad?: string; entidad_id?: string; usuario_id?: string;
    fecha_desde?: string; fecha_hasta?: string; page?: number
  }) => api.get('/auditoria', { params }),
}

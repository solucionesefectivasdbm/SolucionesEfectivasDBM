// ─── Enums ───────────────────────────────────────────────────────────────────

export type TipoUsuario = 'admin' | 'registrador' | 'recaudador' | 'gestor'
export type TipoCredito = 'cuota_fija' | 'abono_capital'
export type Periodicidad = 'mensual' | 'quincenal' | 'semanal' | 'diario'
export type TipoCuota = 'programada' | 'no_programada' | 'interes' | 'abono'
export type DestinoExcedente = 'capital' | 'intereses'
export type TipoValidacion = 'completo' | 'incompleto' | 'con_excedente'
export type TipoCuenta = 'Ahorros' | 'Corriente'
export type Momento = 'm1' | 'm2' | 'm3' | 'm4' | 'm5'

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface Usuario {
  id: string
  username: string
  telefono: string
  tipo_usuario: TipoUsuario
  activo: boolean
  must_change_password: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: Usuario
}

// ─── Receptor ────────────────────────────────────────────────────────────────

export interface CuentaBancaria {
  id: string
  receptor_id: string
  entidad_bancaria: string
  tipo_cuenta: TipoCuenta
  numero_cuenta: string
}

export interface Receptor {
  id: string
  nombre: string
  cedula: string
  telefono: string
  cuentas_bancarias: CuentaBancaria[]
}

// ─── Gestor ───────────────────────────────────────────────────────────────────

export interface Gestor {
  id: string
  user_id: string
  cedula: string
  nombre: string
  apellidos: string
  telefono: string
  direccion: string
  correo_electronico: string
  receptor_id: string | null
  receptor: Receptor | null
}

// ─── Cliente ──────────────────────────────────────────────────────────────────

export interface Cliente {
  id: string
  gestor_id: string
  nombre: string
  apellidos: string
  cedula: string
  telefono: string
  direccion: string
  correo_electronico: string | null
  afiliacion_militar: boolean
  al_dia: boolean
}

// ─── Crédito ──────────────────────────────────────────────────────────────────

export interface Credito {
  id: string
  cliente_id: string
  numero_credito_cliente: string
  tipo_credito: TipoCredito
  capital_prestado: number
  tasa_interes_mensual: number
  fecha_apertura: string
  fecha_inicial_pago: string
  periodicidad: Periodicidad
  saldo_capital: number
  saldo_intereses: number
  abono_minimo: number | null
  numero_cuotas: number | null
  calcular_interes_dias_corridos: boolean
  activo: boolean
}

// ─── Pago ─────────────────────────────────────────────────────────────────────

export interface Pago {
  id: string
  credito_id: string
  numero_cuota: number
  tipo_cuota: TipoCuota
  monto_a_pagar: number
  capital_a_pagar: number
  interes_a_pagar: number
  capital_pagado: number
  interes_pagado: number
  momento: string
  fecha_maxima: string
  receptor_id: string | null
  pagado: boolean
  validado_recaudador: boolean
  fecha_pago_real: string | null
  es_excedente_a: DestinoExcedente | null
  es_ultimo_pago: boolean
  tipo_validacion?: TipoValidacion | null
  cliente_nombre?: string | null
  numero_credito_cliente?: string | null
}

export interface RegistrarPagoResponse {
  pago: Pago
  requiere_decision: boolean
  excedente: number | null
  mensaje: string
}

// ─── Reporte ──────────────────────────────────────────────────────────────────

export interface ReporteDetalleGestor {
  gestor_id: string
  gestor_nombre: string
  total_recaudado: number
  total_intereses: number
  total_capital: number
}

export interface ReporteDetalleReceptor {
  receptor_id: string
  receptor_nombre: string
  total_recaudado: number
  total_intereses: number
  total_capital: number
}

export interface Reporte {
  anio: number
  mes: number
  momento: string
  total_recaudado: number
  total_intereses: number
  total_capital: number
  por_gestor: ReporteDetalleGestor[]
  por_receptor: ReporteDetalleReceptor[]
}

// ─── Paginación ───────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// ─── Alertas ──────────────────────────────────────────────────────────────────

export interface AlertasVencidos {
  total_pagos_vencidos: number
  total_monto_mora: number
  pagos: Pago[]
}

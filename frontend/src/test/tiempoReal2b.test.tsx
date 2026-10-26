import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import type { EventoTiempoReal } from '../api/tipos';
import { AuthProvider } from '../auth/AuthContext';
import { TiempoRealProvider, useEventoTiempoReal } from '../tiempo_real/TiempoRealContext';
import { abrirSocket, iniciarSesionComo, instalarWebSocketFalso, simularFetch } from './utiles';

function Oyente({ tipos }: { tipos: EventoTiempoReal['tipo'][] }) {
  const recibidos: string[] = [];
  useEventoTiempoReal(tipos, (e) => {
    recibidos.push(e.tipo);
    const nodo = document.getElementById('salida')!;
    nodo.textContent = `${nodo.textContent ?? ''}|${e.tipo}:${JSON.stringify(e.datos)}`;
  });
  return <div id="salida" />;
}

describe('Tiempo real 2B', () => {
  beforeEach(() => {
    iniciarSesionComo('supervisor');
    instalarWebSocketFalso();
    simularFetch();
  });

  it('entrega los eventos nuevos (conversacion.mensaje/estado, atencion.cola, trabajo.fallido) a los suscriptores por tipo', async () => {
    render(
      <AuthProvider>
        <TiempoRealProvider>
          <Oyente tipos={['conversacion.mensaje', 'conversacion.estado', 'atencion.cola', 'trabajo.fallido']} />
        </TiempoRealProvider>
      </AuthProvider>,
    );
    const ws = await abrirSocket(1, 'supervisor');
    const emitir = (tipo: string, datos: unknown) => act(() => ws.recibir({ tipo, datos, emitido_en: '2026-10-24T15:00:00Z' }));
    emitir('conversacion.mensaje', { conversacion_id: 12, mensaje_id: 101, campana_id: 1, usuario_asignado_id: 5, direccion: 'entrante', autor: 'cliente', estado: 'recibido', accion: 'nuevo' });
    emitir('conversacion.estado', { conversacion_id: 12, campana_id: 1, estado: 'abierta', atendida_por: 'humano', usuario_asignado_id: 5, usuario_anterior_id: null, motivo_cierre: null });
    emitir('atencion.cola', { cola_id: 40, conversacion_id: 12, campana_id: 1, motivo: 'entrante', accion: 'encolada' });
    emitir('trabajo.fallido', { trabajo_id: 88, tipo: 'whatsapp.enviar_mensaje', codigo: '63003' });
    emitir('agente.estado', { usuario_id: 1 }); // no suscrito: se ignora
    const salida = screen.getByText((_, el) => el?.id === 'salida').textContent!;
    expect(salida.split('|').filter(Boolean).map((x) => x.split(':')[0])).toEqual([
      'conversacion.mensaje', 'conversacion.estado', 'atencion.cola', 'trabajo.fallido',
    ]);
    expect(salida).toContain('"mensaje_id":101');
    expect(salida).toContain('"codigo":"63003"');
  });
});

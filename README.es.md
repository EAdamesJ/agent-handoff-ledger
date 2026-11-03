# Registro de traspasos entre agentes

Un registro local compartido para Claude Code, Codex y DeepSeek Harness. Guarda el objetivo, el estado, el resumen del traspaso y la siguiente acción. Una sola instancia participante puede tener el turno de escritura del proyecto y cada tarea tiene un máximo de traspasos para evitar ciclos largos.

## Por qué

Conectar dos agentes es sencillo. Mantener el estado de la tarea, decidir quién escribe y evitar que ambos cambien los mismos archivos es lo difícil. Este servidor MCP conserva una ficha compartida en SQLite y exige que cada agente reclame el turno antes de escribir.

## Inicio rápido

Requiere Python 3.11+ y `uv`. Registra el servidor local en cada cliente MCP que quieras usar:

- Claude Code: `.mcp.json` del proyecto.
- Codex: `~/.codex/config.toml` o `.codex/config.toml` de un proyecto confiable.
- DeepSeek Harness: `@deepseek-ai/dsh-mcp-client`.

Los ejemplos completos están en el [README en inglés](README.md). Reemplaza la ruta del proyecto por una ruta absoluta igual en los tres clientes.

## Flujo

1. `create_handoff` guarda el objetivo y el agente destino.
2. `claim_handoff` entrega un único turno de escritura.
3. `pass_handoff` guarda el resumen y la próxima acción, y libera el turno; o `complete_handoff` termina la tarea.
4. El agente siguiente reclama antes de escribir.

El límite predeterminado es cuatro traspasos por tarea. El servidor no llama modelos, no ejecuta comandos y no hace solicitudes de red. La coordinación es cooperativa: solo afecta a los agentes que usan este MCP.

## Investigación

La búsqueda pública encontró una demanda clara por colaboración entre agentes y un hueco más concreto en el estado compartido, la exclusión de escritor y los límites de ciclo. La cobertura de publicaciones en Threads, Instagram y grupos de Facebook no es pública o indexable de forma suficiente para medir demanda; la investigación completa y los enlaces están en [`docs/market-research.md`](docs/market-research.md).

## Licencia

MIT. Ver [LICENSE](LICENSE).
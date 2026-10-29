# Lo que dejé afuera a propósito

1. **Concurrencia.** Si dos procesos corren a la vez, los dos pueden ver "no existe" y crear la
   orden. Se resuelve con un lock (o con que la API respete `client_ref`). Para un script que corre
   de a uno, no lo justifica.
2. **Throttling proactivo.** Ante un 429 espero lo que dice `Retry-After-Ms` (4s), pero la ventana
   real es de 60s, así que a veces reintenta varias veces seguidas. Un rate limiter del lado del
   cliente lo evitaría, aunque igual no alcanza: el límite es compartido con otros clientes.
3. **Reconciliar órdenes duplicadas previas.** Si ya hay varias órdenes con el mismo `client_ref`
   (de antes de este script), aviso y reporto la primera. No las cancelo: no hay endpoint para eso
   y no me corresponde decidirlo.
4. **Pedir una segunda orden igual a propósito.** El `client_ref` sale de location + item + cantidad,
   así que la misma combinación no se repite nunca. En un caso real la clave vendría del id del
   pedido en el sistema de origen.
5. **Datos del cliente** (`customer` en la doc). No es obligatorio y el ejercicio no lo pide.
6. **Configuración y secretos.** Las credenciales del mock están en el código. En producción irían
   en variables de entorno o en un secret manager.
7. **Tests automatizados.** Lo probé a mano contra el mock (doble corrida, 500, 429, token vencido,
   item inexistente o no disponible, location inválida, server caído). Lo siguiente sería un test
   suite que levante el mock.
8. **Logging estructurado y métricas.** Hoy son prints a stderr.
9. **Más de un item por orden y matching difuso de nombres.** Comparo nombres exactos, ignorando
   mayúsculas y espacios extra.
10. **Usar `created_at`.** Está mal (dice UTC y no lo es) y el resumen no lo necesita.

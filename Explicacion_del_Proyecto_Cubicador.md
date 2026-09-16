# El proyecto Cubicador, explicado sin tecnicismos

Este documento es para alguien que no sabe nada de programación y quiere entender, de principio a fin, qué se ha estado construyendo, cómo funciona, y qué son todas estas palabras raras (GitHub, Streamlit, Claude, commits...).

---

## 1. ¿Qué problema resuelve esto?

Cada Centro de Distribución (CD) recibe un pedido: "de este producto, tantas cajas; de este otro, tantas más", etc. Alguien tiene que decidir **cómo acomodar físicamente esas cajas en pallets** — qué va en cada pallet, cuántas cajas caben, en qué posición, sin que el pallet quede demasiado bajo (desperdicia el camión) ni demasiado alto (inseguro, o se cae).

Hacer esto a mano, CD por CD, SKU por SKU, es lento y depende de la experiencia de la persona. El proyecto construye un **programa de computadora** que hace ese cálculo automáticamente: le das un Excel con el pedido, las medidas de las cajas y las reglas del Maestro de SKUs, y te devuelve un plan: "en el pallet 1 va esto, en el pallet 2 va esto otro", con la altura y el peso resultante de cada uno.

---

## 2. ¿Qué es "el código"?

El código es, literalmente, un conjunto de instrucciones escritas en un lenguaje muy preciso (en este caso, un lenguaje llamado **Python**) que la computadora sigue al pie de la letra. Es como una receta de cocina extremadamente detallada: "toma este dato, compáralo con este otro, si es mayor haz esto, si no haz esto otro, repite hasta que...".

El código de este proyecto está organizado en **archivos** (cada uno con una responsabilidad), y cada archivo tiene funciones que hacen una tarea concreta. Por ejemplo, hay un archivo que solo se encarga de revisar que los datos del Excel estén bien escritos, otro que decide qué cajas entran en un pallet, otro que arma el Excel de salida, etc. Es como tener distintos empleados especializados: uno revisa el pedido, otro acomoda las cajas, otro hace el reporte final — y el código va pasando el trabajo de uno a otro en orden.

### ¿Qué hace el motor, en plata?

En términos simples, el programa sigue estos pasos, en este orden:

1. **Lee el Excel** (el pedido, el Maestro de SKUs, y las medidas de las cajas) y revisa que los datos tengan sentido (por ejemplo, que ninguna caja sea más grande que el pallet).
2. **Calcula cuántas cajas de cada producto entran en una capa (una "cama")** del pallet, cruzando lo que dice el Maestro con la medida real de la caja.
3. **Arma cada pallet capa por capa** (como si fuera un pastel de varios pisos): elige qué producto va primero en la capa de abajo, la llena, y solo agrega otro producto a esa misma capa si tiene una altura de caja parecida (para no dejar huecos de aire grandes). Cuando la capa está lista, sube y arma la siguiente, hasta llegar a la altura máxima permitida (entre 190 y 215 cm).
4. **Revisa el resultado**: que ningún pallet se pase de peso o de altura, que ninguna caja quede flotando fuera del pallet, que no se haya "perdido" ninguna caja del pedido en el camino.
5. **Genera el Excel final** con el plan de picking: qué va en cada pallet, y un resumen por CD.

Todo esto corre en segundos. Una persona haciendo esto a mano tardaría horas.

---

## 3. ¿Cómo hace Claude para modificar el código?

Yo (Claude) no "toco" la computadora con las manos como una persona — trabajo con **herramientas** que me permiten:

- **Leer archivos**: abro el archivo de código y veo exactamente qué dice, línea por línea.
- **Escribir o editar archivos**: cambio una parte del texto del código (por ejemplo, cambio el número "190" por "195" si la regla de altura mínima cambia), o agrego un archivo nuevo si hace falta una función nueva.
- **Ejecutar el programa**: puedo "correr" el código con datos de prueba (o con el Excel real) para ver qué resultado da, y así comprobar si el cambio que hice funciona como se esperaba, antes de darlo por bueno.
- **Correr pruebas automáticas ("tests")**: el proyecto tiene más de 100 mini-comprobaciones escritas de antemano (por ejemplo: "ningún pallet debe superar 215cm de altura", "nunca se debe perder una caja del pedido"). Cada vez que se cambia algo, se pueden correr todas esas comprobaciones de golpe para asegurarse de que el cambio no rompió nada que ya funcionaba.

En la práctica, el trabajo se hizo de dos maneras a lo largo del proyecto:

- **Dentro de esta conversación (Cowork)**: Omar me pide algo en lenguaje normal ("cambia la altura mínima a 190cm", "revisa por qué me da pallets muy bajos"), yo leo el código relevante, lo modifico, corro pruebas para confirmar que funciona, y le devuelvo un resumen de qué cambié.
- **Con Claude Code, por fuera de esta conversación**: Omar también usa una herramienta llamada **Claude Code**, que es una versión de Claude pensada para trabajar directamente en la computadora de Omar, con acceso a la carpeta real del proyecto. Ahí Omar le da instrucciones parecidas ("arma el pallet por capas, no por columnas"), y Claude Code edita los archivos reales, corre las pruebas, y dejó un registro escrito de cada cambio grande en un archivo llamado `PATCH_LOG.md` (una especie de bitácora). Esto explica por qué, cuando yo vuelvo a leer el código en esta conversación, a veces encuentro cosas que cambiaron sin que yo las hubiera tocado — fueron cambios hechos por esa otra sesión de Claude Code, y yo los detecto leyendo el código de nuevo y los explico.

En ningún caso el código se modifica "solo" o al azar: cada cambio es una instrucción concreta de Omar, ejecutada por una IA que edita texto y corre pruebas, igual que lo haría un programador humano — solo que mucho más rápido.

---

## 4. ¿Dónde está guardado todo esto?

Todo el proyecto vive en una **carpeta normal, en el computador de Omar**: `Documents/Agent Cubicador/agente-cubicador-transportes-bees`. Adentro hay:

- Los **archivos de código** (`.py`), organizados en subcarpetas.
- Los **Excel de ejemplo/reales** que se usaron para probar el motor.
- Los **documentos explicativos** (como este, y los dos técnicos: `DOCUMENTACION_LOGICA.md` y `DOCUMENTACION_TECNICA.md`).
- Una carpeta oculta llamada `.git`, que es la que le da a esa carpeta "memoria" de todos los cambios (ver punto 5).

No hay ningún servidor misterioso ni nube compleja involucrada para el código en sí: es una carpeta de archivos de texto, como cualquier carpeta de Word o Excel, solo que con instrucciones de programación en vez de texto normal.

---

## 5. ¿Qué es GitHub (y "Git")?

Imaginate que estás editando un documento en Google Docs y usás el historial de versiones para ver "quién cambió qué, cuándo, y por qué" — y podés volver a una versión de hace una semana si algo salió mal. **Git** es esa misma idea, pero pensada para código: cada vez que se guarda un avance importante, se crea una fotografía exacta de cómo estaba el código en ese momento, con un mensaje explicando qué se cambió y por qué. A esa fotografía se le llama **commit**.

En este proyecto, cada commit tiene un mensaje detallado (por ejemplo: *"refactor: armado por camas, no por torres verticales"*) que explica qué se cambió, por qué, y qué resultado dio. Eso permite:

- Ver la **historia completa** del proyecto, paso a paso, desde el primer día.
- Volver atrás si un cambio resultó ser un error.
- Entender, meses después, por qué el código quedó como quedó (la razón de negocio detrás de cada número o regla).

**GitHub** es, en pocas palabras, una versión de Git guardada "en la nube" (en un sitio web), para poder acceder al historial desde cualquier lado y, si hiciera falta, compartirlo con otra persona. En este proyecto puntual, el trabajo se ha hecho sobre todo de forma **local** (guardado en la computadora de Omar, con Git llevando el historial ahí mismo) — GitHub como sitio web todavía no forma parte central del flujo de trabajo, pero es la pieza que existiría si en algún momento se quisiera compartir el código con otro desarrollador o tenerlo respaldado en línea.

---

## 6. ¿Qué es Streamlit?

Todo lo anterior (el código, los archivos, Git) es invisible para alguien que no programa — nadie de operaciones va a abrir archivos de código para generar un plan de picking. Para eso existe **Streamlit**: una herramienta que convierte el código de Python en una **página web sencilla**, con botones, casillas para subir archivos, y tablas — sin necesidad de escribir ni una línea de código para usarla.

En este proyecto, `app.py` es esa página: quien la abre puede subir el Excel del pedido, apretar un botón que dice "Procesar", y ver en pantalla el plan de picking resultante (cuántos pallets, qué llevó cada uno, alertas si algo quedó raro), con la opción de descargar el Excel final. Por dentro, esa página está llamando exactamente al mismo motor descrito en la sección 2 — Streamlit es solo la "cara visible" para que cualquier persona lo use sin tocar código.

---

## 7. La historia del proyecto, resumida

El proyecto no salió perfecto a la primera — fue una seguidilla de versiones, cada una corrigiendo algo que se detectó mirando resultados reales:

1. **Primera versión**: un motor que agrupaba las cajas por categoría (Licores, Lácteos, etc.) en capas separadas, con reglas fijas de qué categoría puede ir arriba de cuál.
2. Se ajustaron **parámetros de negocio**: altura mínima/máxima del pallet, peso máximo, cómo tratar el peso de las cajas, cómo agrupar categorías por tamaño de caja en vez de por tipo.
3. Se comparó el resultado del programa contra **fotos reales de pallets armados por los operarios**, y se descubrió que la operación real mezcla categorías libremente y arma por capas de altura parecida, no por categoría — así que se rediseñó el motor para reflejar eso.
4. Se probó una arquitectura por **"torres"** (cada producto en su propia columna, con su propia altura) que resultó tener un problema: dejaba huecos de aire grandes entre columnas de altura distinta.
5. Se corrigió a la versión actual, que arma **capa por capa** ("cama por cama"), llenando cada nivel horizontal antes de subir al siguiente — la que refleja mejor cómo se arma un pallet en la vida real, confirmado con capturas de pantalla del propio sistema comparadas contra fotos físicas.
6. En paralelo, se validó y ajustó la **geometría** (cuántas cajas entran realmente en un pallet según sus medidas físicas), incorporando mediciones reales hechas por el equipo de operaciones.

Cada uno de estos pasos quedó documentado con evidencia concreta (números de antes/después, fotos, mediciones) — no son cambios "porque sí", sino ajustes justificados y comprobados cada vez contra datos reales.

---

## 8. Glosario rápido

| Palabra | Qué significa en este proyecto |
|---|---|
| **Código** | Las instrucciones escritas que la computadora ejecuta para hacer el cálculo |
| **Python** | El lenguaje de programación en el que está escrito el código |
| **SKU** | Un producto específico (una referencia) |
| **CD** | Centro de Distribución |
| **Pallet** | La base de madera/plástico sobre la que se apilan las cajas para moverlas |
| **Cama** | Una capa horizontal de cajas dentro de un pallet |
| **Excel de entrada** | El pedido + el Maestro de SKUs + las medidas de las cajas (UMA) |
| **Plan de picking** | El Excel de salida: qué va en cada pallet |
| **Git** | El sistema que guarda el historial de cambios del código |
| **Commit** | Una "fotografía" guardada del código en un momento dado, con explicación de qué cambió |
| **GitHub** | Un sitio web para guardar/compartir ese historial en la nube |
| **Streamlit** | La herramienta que convierte el código en una página web usable sin programar |
| **Claude Code** | La versión de Claude que trabaja directo sobre los archivos en la computadora de Omar |
| **Test / prueba** | Una comprobación automática que verifica que una regla del negocio se sigue cumpliendo |
| **Benchmark** | La comparación del resultado del programa contra pallets armados de verdad, para medir qué tan bien se acerca a la realidad |

---

Si algo de esto no queda claro con una sola lectura, es normal — es un proyecto que combina reglas de negocio de logística con conceptos de programación que no son intuitivos si uno no los usa todos los días. La idea de este documento es que sirva como mapa: cualquiera que lo lea debería poder ubicar, al menos, "en qué parte del proyecto estamos parados" y "por qué existe cada pieza".

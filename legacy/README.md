# legacy/ — snapshot V4

Copia congelada del core V4 (camas) tal como estaba al empezar V5-P1, para
poder diffear y para referencia de rollback -ver `PLAN_IMPLEMENTACION_PARCHES_V5.md`.

**Estas copias NO se importan en ningún lado.** El camino `PACKER_VERSION = "V4"`
sigue usando los módulos activos en `src/` (`src/packing_2d.py`,
`src/apilado_3d.py`, `src/pallets_homogeneos.py`) -reescribir todos los
imports del repo para apuntar a `legacy/` mientras V4 sigue siendo el default
de producción hubiera sido más riesgo que beneficio (dos copias del mismo
código activo, fácil que diverjan). Cuando V5 pase el gate (V5-P14) y se
retire V4 de verdad (V5-P16), estas copias en `legacy/` son las que quedan
como referencia histórica -recién ahí `src/packing_2d.py` etc. se
reemplazan por el core V5.

"""[EJEMPLO DE REFERENCIA -target de éxito para "grandes primero", NO parte
del pipeline real] Reconstrucción exacta, caja por caja, del pallet BK31
(CD Cañete) armado a MANO en una sesión de chat completa -no generado por
el motor. Representa la demanda REAL de BK31 en `Plantilla_Ejemplo_Agente_
Cubicador (1) (3).xlsx` (`Pallets_Objetivo=1`): 98 cajas, 12 SKUs (más
Pall Mall Boost/Sunrise, que van aparte en la caja de consolidación de
Cigarros, ver src/bat.py -no entran acá).

Por qué existe: el motor real (`src.packing_bloques`, camino de
`Pallets_Objetivo`), con la mejor heurística lograda hasta ahora, coloca
87/98 (ver Parches/v5/PATCH_LOG.md, sección "Grandes primero"). Este
script demuestra que SÍ es geométricamente posible llegar a 98/98 en el
mismo pallet -es la prueba de que la brecha es de algoritmo, no de espacio
físico. Ver Parches/v5/DISENO_STRIP_PACKING_GRANDES.md para el diseño
propuesto que debería cerrar esa brecha, y el README de esta carpeta para
el detalle de las decisiones de armado (por qué cada SKU quedó donde
quedó).

Corrarlo regenera las 6 vistas (isométrica, frontal, trasera, laterales,
superior) en /tmp/ -requiere matplotlib (no es una dependencia del
proyecto real, instalar aparte si hace falta: `pip install matplotlib`)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

cajas = []
def add(sku, x, y, z, largo, ancho, alto, cantidad):
    for i in range(cantidad):
        cajas.append({'sku': sku, 'x': x, 'y': y, 'z': z+i*alto, 'dx': largo, 'dy': ancho, 'dz': alto})

# Cama1 (Z=0)
for j in range(3):
    for i in range(4):
        add('15506', i*24, j*31, 0, 24, 31, 30.5, 1)
for i in range(3):
    add('15506', i*31+7, 93, 0, 31, 24, 30.5, 1)
# Cama2 (Z=30.5)
xs2 = [4,28,52,76]
for y in [27,58,89]:
    for x in xs2:
        add('15506', x, y, 30.5, 24, 31, 30.5, 1)
for x in [7,38,69]:
    add('15506', x, 3, 30.5, 31, 24, 30.5, 1)
# Cama3 (Z=61.0)
for j in range(3):
    for i in range(4):
        add('15506', i*24, j*31, 61.0, 24, 31, 30.5, 1)
for i in range(3):
    add('15506', i*31+7, 93, 61.0, 31, 24, 30.5, 1)
# Cama4 (Z=91.5)
for y in [27,58]:
    for x in xs2:
        add('15506', x, y, 91.5, 24, 31, 30.5, 1)
for x in [7,38,69]:
    add('15506', x, 3, 91.5, 31, 24, 30.5, 1)
add('15506', 76, 89, 91.5, 24, 31, 30.5, 1)
add('22726', 1.8, 89, 91.5, 23.2, 31.1, 30.2, 1)
add('22713', 25.0, 89, 91.5, 17.0, 28.5, 21.5, 2)
add('22713', 42.0, 89, 91.5, 17.0, 28.5, 21.5, 2)
add('22712', 59.0, 89, 91.5, 17.0, 28.5, 21.5, 2)

# Gaseosa Oro -corrida a x=32.5 (confirmada)
for i in range(5):
    add('22715', 32.5, 3+i*17.0, 122.0, 28.5, 17.0, 21.5, 1)

# 3 Picaras confirmadas (por demanda desc): Mini, Extremas, Fresa
add('19685', 61, 0, 122.0, 39.0, 30.0, 28.5, 1)
add('21191', 61, 30, 122.0, 39.0, 30.0, 28.5, 1)
add('21850', 61, 60, 122.0, 39.0, 30.0, 28.5, 1)

# Picaras Mini adicionales en la franja izquierda de la Gaseosa Oro (x:1.8-32.5)
# Ancho=30 en Frente, Largo=39 en Fondo (misma rotacion que las de la derecha)
add('19685', 1.8, 3, 122.0, 30.0, 39.0, 28.5, 1)
add('19685', 1.8, 42, 122.0, 30.0, 39.0, 28.5, 1)

# --- Cama 6: mismas 5 posiciones de la cama 5, apiladas encima (z=150.5) ---
# 2 Mini (izquierda, agota las 2 pendientes) + 3 Extremas (derecha, agota las 3 pendientes)
add('19685', 1.8, 3, 150.5, 30.0, 39.0, 28.5, 1)
add('19685', 1.8, 42, 150.5, 30.0, 39.0, 28.5, 1)
add('21191', 61, 0, 150.5, 39.0, 30.0, 28.5, 1)
add('21191', 61, 30, 150.5, 39.0, 30.0, 28.5, 1)
add('21191', 61, 60, 150.5, 39.0, 30.0, 28.5, 1)

# AM Cafe apoyada directo sobre la repisa de las 3 KR (z=134.5).
add('20233', 25.0, 89, 134.5, 35.0, 27.0, 13.0, 3)
# 4 Altomayo apiladas encima del Vino (24 ancho, la caja mide 25.7 -sobresale 1.7cm, aceptado)
# -la 4ta completa la demanda total de Altomayo (6/6: 4 aqui + 2 giradas sobre KR)
add('23486', 76.0, 89, 122.0, 25.7, 26.0, 17.0, 4)
# 1 Altomayo girada (Alto=17 como base, pegada al KR) en el resto libre de la repisa KR (x:60-76, 16 ancho)
add('23486', 60.0, 89, 134.5, 17.0, 26.0, 25.7, 2)

# Ultima Fresa (Picaras), acostada: su Alto (28.5) calza exacto como base en la
# franja libre sobre la Gaseosa Oro (28.5x85, piso 143.5) -39cm de fondo, 30cm de alto (mas bajo/estable).
# Corrida al fondo (y=49, contra el limite real de soporte/colision -la Gaseosa
# Oro solo sostiene hasta y=88, y de ahi para atras ya esta el AM Cafe a z=134.5-147.5,
# que se metería en el rango de altura de la Fresa) -queda pegada a los Altomayo/AM Cafe.
add('21850', 32.5, 49, 143.5, 28.5, 39.0, 30.0, 1)

# Pringles (5, 29x22.5x13): acostadas con Alto(13)xAncho(22.5) como base y el
# Largo(29) parado como altura -asi entran en grid 2x2 en la franja delante de
# la Fresa (28.5x46, piso 143.5). La 5ta se apila encima de una de las 4
# (mismo SKU, no relleno mixto -mismo criterio usado en toda la sesion).
add('22176', 32.5, 3.0, 143.5, 13.0, 22.5, 29.0, 1)
add('22176', 32.5, 25.5, 143.5, 13.0, 22.5, 29.0, 1)
add('22176', 45.5, 3.0, 143.5, 13.0, 22.5, 29.0, 1)
add('22176', 45.5, 25.5, 143.5, 13.0, 22.5, 29.0, 2)

# Molitalia (4, 47x13x10): el Largo (47) no entra acostado en ningun lado libre
# -se paran sobre su base chica (10x13), Largo como altura (47cm). Calzan
# EXACTO en grid 2x2 en el espacio libre sobre el Vodka (23.2x31, piso 121.7),
# terminando toda la demanda de Molitalia.
add('22354', 1.8, 89.0, 121.7, 10.0, 13.0, 47.0, 1)
add('22354', 1.8, 102.0, 121.7, 10.0, 13.0, 47.0, 1)
add('22354', 11.8, 89.0, 121.7, 10.0, 13.0, 47.0, 1)
add('22354', 11.8, 102.0, 121.7, 10.0, 13.0, 47.0, 1)

print(f"Total cajas: {len(cajas)}")

CAT = {
    '15506': ('Licores', '#1E4A94'), '22726': ('Licores', '#A83232'),
    '22713': ('NABs', '#2E8B57'), '22712': ('NABs', '#3CB371'), '22715': ('NABs', '#D4A017'),
    '19685': ('Comestibles', '#E67E22'), '21191': ('Comestibles', '#E74C3C'), '21850': ('Comestibles', '#F39C12'),
    '22354': ('Comestibles', '#16A085'), '20233': ('Comestibles', '#C0392B'), '23486': ('Comestibles', '#8E44AD'),
    '22176': ('Comestibles', '#2C3E50'),
}

# ============ 1. ISOMETRICA 3D ============
fig = plt.figure(figsize=(11, 11))
ax = fig.add_subplot(111, projection='3d')
for c in cajas:
    x, y, z = c['x'], c['y'], c['z']
    dx, dy, dz = c['dx'], c['dy'], c['dz']
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    v = [
        [x,y,z],[x+dx,y,z],[x+dx,y+dy,z],[x,y+dy,z],
        [x,y,z+dz],[x+dx,y,z+dz],[x+dx,y+dy,z+dz],[x,y+dy,z+dz],
    ]
    faces = [
        [v[0],v[1],v[2],v[3]], [v[4],v[5],v[6],v[7]],
        [v[0],v[1],v[5],v[4]], [v[2],v[3],v[7],v[6]],
        [v[1],v[2],v[6],v[5]], [v[0],v[3],v[7],v[4]],
    ]
    poly = Poly3DCollection(faces, facecolor=color, edgecolor='white', linewidths=0.4, alpha=1.0)
    ax.add_collection3d(poly)
ax.set_xlim(0, 100); ax.set_ylim(0, 120); ax.set_zlim(0, 215)
ax.set_xlabel('Frente (cm)'); ax.set_ylabel('Fondo (cm)'); ax.set_zlabel('Altura (cm)')
ax.set_box_aspect([100,120,215])
ax.view_init(elev=22, azim=-60)
ax.set_title('BK31 -Estado actual -Vista isométrica')
leyenda = {}
for sku, (cat, color) in CAT.items():
    if any(c['sku']==sku for c in cajas):
        leyenda[f'{sku} ({cat})'] = color
handles = [patches.Patch(color=c, label=l) for l, c in leyenda.items()]
ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=7)
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_isometrica.png', dpi=150, bbox_inches='tight')
plt.close()
print("Isometrica guardada")

# ============ 2. VISTA FRONTAL (X vs Z) ============
fig, ax = plt.subplots(figsize=(10, 8))
cajas_frontal = sorted(cajas, key=lambda c: -c['y'])
for c in cajas_frontal:
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    ax.add_patch(patches.Rectangle((c['x'], c['z']), c['dx'], c['dz'], facecolor=color, edgecolor='white', linewidth=0.3))
ax.set_xlim(0, 100); ax.set_ylim(0, 215)
ax.set_xlabel('Frente del pallet (cm)'); ax.set_ylabel('Altura (cm)')
ax.set_title('BK31 -Estado actual -Vista frontal')
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_frontal.png', dpi=150)
plt.close()
print("Frontal guardada")

# ============ 2b. VISTA TRASERA (X espejado: 100 - x - dx) ============
fig, ax = plt.subplots(figsize=(10, 8))
cajas_trasera = sorted(cajas, key=lambda c: c['y'])
for c in cajas_trasera:
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    x_mirror = 100 - c['x'] - c['dx']
    ax.add_patch(patches.Rectangle((x_mirror, c['z']), c['dx'], c['dz'], facecolor=color, edgecolor='white', linewidth=0.3))
ax.set_xlim(0, 100); ax.set_ylim(0, 215)
ax.set_xlabel('Frente del pallet (cm)'); ax.set_ylabel('Altura (cm)')
ax.set_title('BK31 -Estado actual -Vista trasera')
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_trasera.png', dpi=150)
plt.close()
print("Trasera guardada")

# ============ 3. VISTA LATERAL (Y vs Z) ============
fig, ax = plt.subplots(figsize=(9, 8))
cajas_lateral = sorted(cajas, key=lambda c: -c['x'])
for c in cajas_lateral:
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    ax.add_patch(patches.Rectangle((c['y'], c['z']), c['dy'], c['dz'], facecolor=color, edgecolor='white', linewidth=0.3))
ax.set_xlim(0, 120); ax.set_ylim(0, 215)
ax.set_xlabel('Fondo del pallet (cm)'); ax.set_ylabel('Altura (cm)')
ax.set_title('BK31 -Estado actual -Vista lateral izquierda')
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_lateral.png', dpi=150)
plt.close()
print("Lateral guardada")

# ============ 3b. VISTA LATERAL DERECHA (mismo eje Fondo, sin espejar) ============
fig, ax = plt.subplots(figsize=(9, 8))
cajas_lateral_d = sorted(cajas, key=lambda c: c['x'])
for c in cajas_lateral_d:
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    ax.add_patch(patches.Rectangle((c['y'], c['z']), c['dy'], c['dz'], facecolor=color, edgecolor='white', linewidth=0.3))
ax.set_xlim(0, 120); ax.set_ylim(0, 215)
ax.set_xlabel('Fondo del pallet (cm)'); ax.set_ylabel('Altura (cm)')
ax.set_title('BK31 -Estado actual -Vista lateral derecha')
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_lateral_derecha.png', dpi=150)
plt.close()
print("Lateral derecha guardada")

# ============ 4. VISTA SUPERIOR (top-down, X vs Y) para la cama mas alta (6) ============
fig, ax = plt.subplots(figsize=(9, 10.5))
cama6 = [c for c in cajas if c['z'] >= 150.5]
for c in cama6:
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    ax.add_patch(patches.Rectangle((c['x'], c['y']), c['dx'], c['dy'], facecolor=color, edgecolor='white', linewidth=1.0))
    ax.text(c['x']+c['dx']/2, c['y']+c['dy']/2, c['sku'], ha='center', va='center', fontsize=6.5, color='white')
ax.set_xlim(0, 100); ax.set_ylim(0, 120); ax.set_aspect('equal')
ax.set_xlabel('Frente (cm)'); ax.set_ylabel('Fondo (cm)')
ax.set_title('BK31 -Cama 6 (piso 150.5cm) -Vista superior')
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_top.png', dpi=150)
plt.close()
print("Top guardada")

# ============ 4b. VISTA SUPERIOR COMPLETA (todo el pallet, tal como se ve desde arriba) ============
fig, ax = plt.subplots(figsize=(9, 10.5))
cajas_arriba = sorted(cajas, key=lambda c: c['z'] + c['dz'])
for c in cajas_arriba:
    color = CAT.get(c['sku'], ('', '#888888'))[1]
    ax.add_patch(patches.Rectangle((c['x'], c['y']), c['dx'], c['dy'], facecolor=color, edgecolor='white', linewidth=0.6))
ax.set_xlim(0, 100); ax.set_ylim(0, 120); ax.set_aspect('equal')
ax.set_xlabel('Frente (cm)'); ax.set_ylabel('Fondo (cm)')
zonas_libres = [
    (1.8, 81, 30.7, 8, 'Franja delant.\n30.7x8cm\npiso 122'),
]
for x, y, w, h, label in zonas_libres:
    ax.add_patch(patches.Rectangle((x, y), w, h, facecolor='none', edgecolor='black', linewidth=2, linestyle='--'))
    ax.text(x+w/2, y+h/2, label, ha='center', va='center', fontsize=7, color='black',
            bbox=dict(facecolor='white', alpha=0.85, edgecolor='none', pad=1))
ax.set_title('BK31 -Espacios completamente libres (nunca construidos)')
plt.tight_layout()
plt.savefig('/tmp/bk31_estado_top_completo.png', dpi=150)
plt.close()
print("Top completo guardada")

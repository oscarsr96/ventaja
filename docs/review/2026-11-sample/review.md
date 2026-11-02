# Revisión en vivo de la capa 1 — muestra de posesiones

- Fecha: 2026-11-02
- Partidos: 114086, 114099, 114169, 114234, 114243, 178442, 179612, 184439, 188630, 191313
- Muestra: n 20 (pedidos 20), seed 7; por regla: gather 10, last_dribble 6, touch_start 4
- Tiros válidos de partida por regla: gather 702, last_dribble 382, touch_start 267
- Modelo: entrenado el 2026-11-02T16:32:43+00:00 con [114086, 114099, 114169, 114234, 114243, 178442, 179612, 184439, 188630, 191313]

Leyenda: atacantes coloreados por el valor ajustado de su opción (viridis, 0,6-1,5 pts), defensores en gris, balón naranja, tirador con borde negro. En el frame de decisión la animación se congela 1 s: círculos huecos en la posición proyectada de cada receptor y flecha roja a la mejor alternativa. En la tabla, `*` es el tirador y `>` la mejor alternativa.

## 1. shot-114086-2-57

regla last_dribble · frame de decisión 54900 · lanzamiento 54930 · reloj 6.4 s · coste 0.496 · good_read no · confidence 1.0

![shot-114086-2-57](shot-114086-2-57.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59158 shot  paint_non_ra      0.26  0.512  1.00  0.512 -           Ziga Samar
>     32336 pass  above_break_3     0.34  1.008  1.00  1.008 extra_pass  Kassius Robertson
      59156 pass  mid_range         0.47  0.935  0.40  0.374 extra_pass  Pierre Pelos
      15347 pass  above_break_3     0.30  0.895  0.40  0.358 extra_pass  Isaiah Wong
      19426 pass  mid_range         0.34  0.684  0.40  0.274 other       Kur Kuath
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: 

## 2. shot-114086-2-60

regla gather · frame de decisión 59035 · lanzamiento 59045 · reloj 5.4 s · coste 0.663 · good_read no · confidence 1.0

![shot-114086-2-60](shot-114086-2-60.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     25182 shot  mid_range         0.19  0.379  1.00  0.379 -           Eric Vila
>     15347 pass  above_break_3     0.37  1.113  0.94  1.042 extra_pass  Isaiah Wong
      59158 pass  above_break_3     0.31  0.940  1.00  0.940 extra_pass  Ziga Samar
      32336 pass  above_break_3     0.37  1.120  0.80  0.894 extra_pass  Kassius Robertson
      19426 pass  paint_non_ra      0.46  0.925  0.40  0.370 post        Kur Kuath
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: 

## 3. shot-114086-3-68

regla last_dribble · frame de decisión 71230 · lanzamiento 71274 · reloj 5.6 s · coste 0.445 · good_read no · confidence 1.0

![shot-114086-3-68](shot-114086-3-68.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     35402 shot  paint_non_ra      0.34  0.676  1.00  0.676 -           Nico Brussino
>     15347 pass  above_break_3     0.37  1.122  1.00  1.122 extra_pass  Isaiah Wong
      59156 pass  above_break_3     0.36  1.078  1.00  1.078 extra_pass  Pierre Pelos
      59158 pass  corner_3          0.37  1.104  0.37  0.404 open_corner Ziga Samar
      19426 pass  paint_non_ra      0.48  0.965  0.40  0.386 post        Kur Kuath
```

Frame de decisión: ok / mal → mal: cuando marca los pasos en la entrada

Opciones valoradas: ok / mal → ok

Comentario: 

## 4. shot-114086-4-102

regla last_dribble · frame de decisión 100737 · lanzamiento 100764 · reloj 12.7 s · coste 0.000 · good_read sí · confidence 1.0

![shot-114086-4-102](shot-114086-4-102.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     22724 shot  restricted_area   0.71  1.419  1.00  1.419 -           Eugene Omoruyi
>     59135 pass  corner_3          0.38  1.151  0.40  0.460 open_corner Matteo Spagnolo
      24949 pass  mid_range         0.35  0.707  0.40  0.283 extra_pass  Markus Howard
      59137 pass  mid_range         0.34  0.672  0.40  0.269 extra_pass  Clement Frisch
      59136 pass  mid_range         0.23  0.464  0.40  0.186 other       Gytis Radzevicius
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok: en este caso la accion es la mejor decision

Comentario: el pase fuera esta tapado por linea de pase

## 5. shot-114169-1-33

regla gather · frame de decisión 27407 · lanzamiento 27417 · reloj 15.7 s · coste 0.538 · good_read no · confidence 1.0

![shot-114169-1-33](shot-114169-1-33.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59090 shot  paint_non_ra      0.48  0.962  1.00  0.962 -           Emanuel Ion Cate
>     59036 pass  above_break_3     0.50  1.500  1.00  1.500 extra_pass  Howard Sant-Roos
       8673 pass  corner_3          0.49  1.458  0.40  0.583 open_corner Zach Hicks
      15362 pass  paint_non_ra      0.50  0.999  0.40  0.400 rim_cut     Michael Forrest
      24504 pass  above_break_3     0.26  0.771  0.40  0.308 other       Jonah Radebaugh
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: 

## 6. shot-114234-1-25

regla last_dribble · frame de decisión 21180 · lanzamiento 21225 · reloj 20.5 s · coste 0.462 · good_read no · confidence 0.7

![shot-114234-1-25](shot-114234-1-25.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     24280 shot  restricted_area   0.54  1.079  1.00  1.079 -           Keandre Cook
>     28410 pass  above_break_3     0.51  1.542  1.00  1.542 extra_pass  Francisco Alonso
      59108 pass  above_break_3     0.28  0.830  1.00  0.830 extra_pass  Bakary Dibba
      59110 pass  backcourt         0.07  0.202  0.29  0.058 other       Danko Brankovic
      59104 pass  backcourt         0.06  0.167  0.24  0.040 other       Dominik Mavra
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: jugador con balon no puede ver la llegada del compañero abierto en el triple

## 7. shot-114234-4-134

regla touch_start · frame de decisión 140300 · lanzamiento 140357 · reloj 5.3 s · coste 0.000 · good_read sí · confidence 1.0

![shot-114234-4-134](shot-114234-4-134.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59106 shot  paint_non_ra      0.43  0.863  1.00  0.863 -           Jordan Sakho
>     58474 pass  paint_non_ra      0.37  0.745  1.00  0.745 post        DeWayne Russell
      59105 pass  mid_range         0.31  0.624  1.00  0.624 extra_pass  Arturs Kurucs
      58771 pass  above_break_3     0.44  1.310  0.40  0.524 extra_pass  Mihajlo Andric
      28410 pass  mid_range         0.37  0.730  0.40  0.292 extra_pass  Francisco Alonso
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: la mejor accion es la ejecutada, hay dos defensores en la zona para dar el pase

## 8. shot-114243-4-140

regla gather · frame de decisión 132131 · lanzamiento 132141 · reloj 3.5 s · coste 0.143 · good_read no · confidence 1.0

![shot-114243-4-140](shot-114243-4-140.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59220 shot  corner_3          0.24  0.733  1.00  0.733 -           Jonathan Rousselle
>     35028 pass  above_break_3     0.38  1.135  0.77  0.876 extra_pass  Matt Thomas
      59217 pass  above_break_3     0.25  0.749  0.34  0.256 other       Luka Bozic
      25326 pass  paint_non_ra      0.32  0.632  0.40  0.253 post        Ivan Aurrecoechea
      25271 pass  mid_range         0.26  0.528  0.38  0.202 extra_pass  Elias Valtonen
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: el pase es arriesgado

## 9. shot-114243-4-155

regla touch_start · frame de decisión 144791 · lanzamiento 144829 · reloj 7.1 s · coste 0.000 · good_read sí · confidence 0.8

![shot-114243-4-155](shot-114243-4-155.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     28247 shot  restricted_area   0.69  1.372  1.00  1.372 -           Zach Hankins
>     59220 pass  above_break_3     0.43  1.285  0.40  0.514 extra_pass  Jonathan Rousselle
      35028 pass  above_break_3     0.34  1.029  0.40  0.412 other       Matt Thomas
      25271 pass  above_break_3     0.32  0.960  0.35  0.341 extra_pass  Elias Valtonen
      59219 pass  mid_range         0.37  0.743  0.40  0.297 extra_pass  Beka Burjanadze
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: buena decision

## 10. shot-179612-2-40

regla gather · frame de decisión 28455 · lanzamiento 28465 · reloj 12.8 s · coste 0.014 · good_read no · confidence 1.0

![shot-179612-2-40](shot-179612-2-40.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     15487 shot  above_break_3     0.44  1.327  1.00  1.327 -           Omari Moore
>     59143 pass  paint_non_ra      0.67  1.342  1.00  1.342 post        Neal Sako
      31587 pass  above_break_3     0.31  0.918  1.00  0.918 extra_pass  Darius Thompson
      59141 pass  mid_range         0.34  0.677  1.00  0.677 other       Jaime Pradilla
      35475 pass  mid_range         0.34  0.673  0.72  0.482 extra_pass  Isaac Nogues
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: buena decision

## 11. shot-179612-3-82

regla gather · frame de decisión 68770 · lanzamiento 68780 · reloj 13.2 s · coste 0.078 · good_read no · confidence 1.0

![shot-179612-3-82](shot-179612-3-82.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59144 shot  above_break_3     0.33  0.988  1.00  0.988 -           Jean Claudio Montero
>     59142 pass  above_break_3     0.36  1.066  1.00  1.066 extra_pass  Brancou Badio
      59143 pass  mid_range         0.27  0.542  1.00  0.542 other       Neal Sako
      59141 pass  mid_range         0.49  0.973  0.40  0.389 extra_pass  Jaime Pradilla
      59140 pass  mid_range         0.30  0.606  0.20  0.120 other       Josep Puerto
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: jugador 0 esta defendido

## 12. shot-179612-4-140

regla gather · frame de decisión 134275 · lanzamiento 134285 · reloj 12.4 s · coste 0.041 · good_read no · confidence 1.0

![shot-179612-4-140](shot-179612-4-140.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     22729 shot  above_break_3     0.37  1.097  1.00  1.097 -           Chris Duarte
>     59127 pass  above_break_3     0.38  1.137  1.00  1.137 extra_pass  Aleksander Balcerowski
      35326 pass  mid_range         0.55  1.094  0.85  0.933 extra_pass  James Webb
      59123 pass  above_break_3     0.45  1.344  0.69  0.930 extra_pass  Alberto Diaz
      24056 pass  mid_range         0.24  0.483  1.00  0.483 other       Killian Tillie
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: buen tiro

## 13. shot-184439-1-20

regla touch_start · frame de decisión 14745 · lanzamiento 14769 · reloj 7.2 s · coste 0.327 · good_read no · confidence 1.0

![shot-184439-1-20](shot-184439-1-20.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59118 shot  paint_non_ra      0.47  0.934  1.00  0.934 -           Giorgi Shermadini
>     59113 pass  above_break_3     0.42  1.261  1.00  1.261 extra_pass  Aaron Doornekamp
      59120 pass  above_break_3     0.25  0.749  1.00  0.749 other       Bruno Fitipaldo
      59116 pass  above_break_3     0.39  1.174  0.40  0.469 extra_pass  Jaime Fernandez Bernabe
      59115 pass  corner_3          0.37  1.123  0.40  0.449 open_corner Thomas Scrubb
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: 

## 14. shot-188630-1-28

regla touch_start · frame de decisión 23320 · lanzamiento 23335 · reloj 10.0 s · coste 0.000 · good_read sí · confidence 1.0

![shot-188630-1-28](shot-188630-1-28.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59156 shot  restricted_area   0.74  1.485  1.00  1.485 -           Pierre Pelos
>     15347 pass  above_break_3     0.45  1.353  1.00  1.353 extra_pass  Isaiah Wong
      59295 pass  above_break_3     0.35  1.051  1.00  1.051 extra_pass  Carlos Alocen
      31539 pass  mid_range         0.29  0.583  1.00  0.583 extra_pass  Chimezie Metu
      35402 pass  mid_range         0.20  0.402  0.40  0.161 other       Nico Brussino
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: no entiendo esta jugada

## 15. shot-188630-4-104

regla gather · frame de decisión 93357 · lanzamiento 93367 · reloj 11.1 s · coste 0.063 · good_read no · confidence 1.0

![shot-188630-4-104](shot-188630-4-104.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59295 shot  above_break_3     0.26  0.784  1.00  0.784 -           Carlos Alocen
>     35402 pass  corner_3          0.28  0.848  1.00  0.848 other       Nico Brussino
      59157 pass  above_break_3     0.32  0.971  0.40  0.388 extra_pass  Mike Tobey
      32336 pass  corner_3          0.53  1.591  0.20  0.320 open_corner Kassius Robertson
      31539 pass  above_break_3     0.33  0.980  0.27  0.262 extra_pass  Chimezie Metu
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: jugador 9 está defendido

## 16. shot-191313-1-10

regla last_dribble · frame de decisión 6580 · lanzamiento 6609 · reloj 18.7 s · coste 0.731 · good_read no · confidence 1.0

![shot-191313-1-10](shot-191313-1-10.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     58474 shot  paint_non_ra      0.41  0.826  1.00  0.826 -           DeWayne Russell
>     59105 pass  corner_3          0.52  1.557  1.00  1.557 open_corner Arturs Kurucs
      59108 pass  paint_non_ra      0.59  1.179  1.00  1.179 rim_cut     Bakary Dibba
      59107 pass  above_break_3     0.31  0.927  1.00  0.927 extra_pass  Aleksandar Aranitovic
      59103 pass  mid_range         0.31  0.622  0.40  0.249 other       Dragan Apic
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: 

## 17. shot-191313-2-46

regla gather · frame de decisión 37615 · lanzamiento 37625 · reloj 5.4 s · coste 0.797 · good_read no · confidence 1.0

![shot-191313-2-46](shot-191313-2-46.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     58474 shot  paint_non_ra      0.37  0.747  1.00  0.747 -           DeWayne Russell
>     59105 pass  corner_3          0.51  1.544  1.00  1.544 open_corner Arturs Kurucs
      59108 pass  above_break_3     0.25  0.749  1.00  0.749 extra_pass  Bakary Dibba
      59103 pass  paint_non_ra      0.36  0.720  1.00  0.720 rim_cut     Dragan Apic
      59107 pass  above_break_3     0.33  0.989  0.40  0.396 extra_pass  Aleksandar Aranitovic
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → mal

Comentario: pase al dorsal 47

## 18. shot-191313-4-122

regla last_dribble · frame de decisión 103185 · lanzamiento 103215 · reloj 9.7 s · coste 0.288 · good_read no · confidence 0.9

![shot-191313-4-122](shot-191313-4-122.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     28410 shot  paint_non_ra      0.35  0.708  1.00  0.708 -           Francisco Alonso
>     59110 pass  paint_non_ra      0.50  0.996  1.00  0.996 rim_cut     Danko Brankovic
      59107 pass  corner_3          0.58  1.739  0.39  0.671 open_corner Aleksandar Aranitovic
      58771 pass  above_break_3     0.45  1.356  0.40  0.542 extra_pass  Mihajlo Andric
      58474 pass  above_break_3     0.25  0.743  0.40  0.297 other       DeWayne Russell
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → ok

Comentario: 

## 19. shot-191313-4-127

regla gather · frame de decisión 110332 · lanzamiento 110342 · reloj 7.9 s · coste 0.342 · good_read no · confidence 1.0

![shot-191313-4-127](shot-191313-4-127.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     58474 shot  above_break_3     0.29  0.862  1.00  0.862 -           DeWayne Russell
>     58771 pass  above_break_3     0.40  1.204  1.00  1.204 extra_pass  Mihajlo Andric
      28410 pass  mid_range         0.36  0.720  1.00  0.720 other       Francisco Alonso
      59110 pass  paint_non_ra      0.50  0.998  0.40  0.399 post        Danko Brankovic
      59107 pass  mid_range         0.21  0.417  0.40  0.167 other       Aleksandar Aranitovic
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → mal

Comentario: pase a dorsal 37

## 20. shot-191313-4-137

regla gather · frame de decisión 131180 · lanzamiento 131190 · reloj 20.9 s · coste 0.134 · good_read no · confidence 1.0

![shot-191313-4-137](shot-191313-4-137.gif)

```text
  player_id type  zone                 P  value  viab    adj alternative name
*     59207 shot  above_break_3     0.27  0.804  1.00  0.804 -           Marco Spissu
>     59206 pass  above_break_3     0.31  0.937  1.00  0.937 extra_pass  Miguel Gonzalez
      31739 pass  mid_range         0.31  0.622  1.00  0.622 other       Trae Bell-Haynes
      35222 pass  above_break_3     0.35  1.050  0.40  0.420 extra_pass  Devin Robinson
      59205 pass  mid_range         0.38  0.759  0.40  0.304 other       Santiago Yusta
```

Frame de decisión: ok / mal → ok

Opciones valoradas: ok / mal → mal

Comentario: tiro precipitado

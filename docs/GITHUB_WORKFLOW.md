# Flujo GitHub

## Remoto

Repositorio principal:

```text
git@github.com:ikerhg88/albaranesparser.git
https://github.com/ikerhg88/albaranesparser
```

La clave SSH generica de Codex en esta maquina es:

```text
C:\Users\ikerh\.ssh\id_ed25519_codexikerhg
```

Verificar:

```powershell
ssh -T git@github.com
git remote -v
```

La respuesta esperada de SSH debe indicar `ikerhg88`.

## Antes De Commit

```powershell
git status --short --ignored
```

No commitear:

- `Albaranes_Pruebas/`
- `debug/`
- `dist/`
- `build/`
- `archive/`
- `temp/`
- `external_bin/`
- `.venv/`
- PDFs, Excels y CSV generados
- `user_settings.json`

## Commit Y Push

```powershell
git add .
git status --short
git commit -m "Descripcion breve"
git push
```

## Diario Por Commit

El repositorio mantiene un diario estricto en:

```text
tracking/logs/commit_diary.md
```

Despues de crear commits:

```powershell
python scripts\update_commit_diary.py
```

Antes de subir:

```powershell
python scripts\update_commit_diary.py --check
rg -n "pendiente de completar|pendiente de clasificar" tracking\logs\commit_diary.md
```

Cada entrada debe explicar tipo de cambio, resumen, validacion e impacto/riesgo. No dejar entradas pendientes.

Los commits que solo modifican `tracking/logs/commit_diary.md` quedan exentos para evitar recursividad con el hash del propio commit. El resto de commits debe tener entrada.

## Si Cambia La Clave SSH

Revisar `C:\Users\ikerh\.ssh\config`. Debe existir una unica entrada efectiva para GitHub:

```text
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_codexikerhg
    IdentitiesOnly yes
```

Si GitHub responde con otro usuario, el primer bloque `Host github.com` esta apuntando a otra clave.

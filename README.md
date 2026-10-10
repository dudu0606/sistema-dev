# Beit - Aulas e Cultos Online (Igreja Batista Nova Betel) (FastAPI + PostgreSQL + OKD)

Perfis: aluno (/portal), pastor (/professor, "Área do Pastor": publica aulas, mapa com nome e local de quem acessou, responde perguntas), admin (/admin: cursos e perfis).
Admin inicial: ADMIN_EMAIL / ADMIN_PASSWORD do secret (padrao: admin@sistema.dev / admin123 - defina o seu!).

## Deploy no OKD
1. Secret `sistema-dev-secrets` no project `sistema-dev` com as chaves:
   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, SECRET_KEY (opcionais: ADMIN_EMAIL, ADMIN_PASSWORD).
2. + > Import YAML > cole `k8s/sistema-dev.yaml` > Create. O OKD baixa o Git, constroi a imagem e sobe tudo.
3. Networking > Routes > sistema-dev.

Atualizar o codigo: push no Git + Builds > sistema-dev-app > Start build.

## Teste local
docker run -d -e POSTGRES_USER=sistema -e POSTGRES_PASSWORD=sistema -e POSTGRES_DB=sistema -p 5432:5432 postgres:16-alpine
pip install -r requirements.txt && COOKIE_SECURE=0 uvicorn app.main:app --reload
